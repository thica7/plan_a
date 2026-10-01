from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx

from packages.config import Settings
from packages.governance import build_model_route_decision
from packages.llm.errors import LLMError, LLMExecutionLimitError
from packages.llm.execution_budget import current_llm_execution
from packages.llm.json_extract import JsonExtractionError, extract_json_object
from packages.schema.enterprise import ModelProviderKind, ModelRouteDecision


class _RetryableLLMError(LLMError):
    pass


_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    provider_kind: ModelProviderKind
    api_key: str
    base_url: str
    model: str


class DoubaoClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_route_decision: ModelRouteDecision | None = None
        self._usage_context: ContextVar[LLMUsage | None] = ContextVar(
            f"usage-{id(self)}", default=None)
        self._response_context: ContextVar[tuple[str, str, str | None] | None] = ContextVar(
            f"response-{id(self)}", default=None)

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: str,
    ) -> dict[str, Any]:
        self._response_context.set(None)
        self._usage_context.set(None)
        json_system = (
            f"{system}\n\n"
            "Return only valid JSON. Do not wrap it in markdown fences. "
            f"The JSON shape is: {schema_hint}"
        )
        providers = self._provider_configs()
        if not providers:
            raise LLMError(self._route_error_message())

        errors: list[str] = []
        for provider in providers:
            try:
                content = await self._complete_text_with_provider(
                    provider,
                    system=json_system,
                    user=user,
                )
                return self._extract_json(content)
            except LLMExecutionLimitError:
                raise
            except Exception as exc:
                safe_error = str(exc).replace(provider.api_key, "[REDACTED]")
                errors.append(f"{provider.name}: {safe_error}")
                self._usage_context.set(None)
        raise LLMError("LLM JSON request failed for all providers: " + " | ".join(errors))

    async def complete_text(self, *, system: str, user: str) -> str:
        self._response_context.set(None)
        self._usage_context.set(None)
        providers = self._provider_configs()
        if not providers:
            raise LLMError(self._route_error_message())

        errors: list[str] = []
        for provider in providers:
            try:
                return await self._complete_text_with_provider(
                    provider,
                    system=system,
                    user=user,
                )
            except LLMExecutionLimitError:
                raise
            except LLMError as exc:
                safe_error = str(exc).replace(provider.api_key, "[REDACTED]")
                errors.append(f"{provider.name}: {safe_error}")
                self._usage_context.set(None)
        raise LLMError("LLM request failed for all providers: " + " | ".join(errors))

    async def _complete_text_with_provider(
        self,
        provider: LLMProviderConfig,
        *,
        system: str,
        user: str,
    ) -> str:
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._settings.llm_temperature,
        }
        self._usage_context.set(None)
        self._response_context.set(None)
        output_limit = self._settings.llm_max_output_tokens
        budget_enabled = self._settings.run_llm_max_tokens or self._settings.run_llm_max_cost_usd
        if not output_limit and budget_enabled:
            output_limit = 4096
        if output_limit:
            payload["max_tokens"] = output_limit
        if provider.name == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "X-Title": "Competiscope",
        }
        url = f"{provider.base_url}/chat/completions"

        attempts = max(1, self._settings.llm_max_retries + 1)
        for attempt in range(attempts):
            try:
                self._response_context.set((provider.name, provider.model, None))
                execution = current_llm_execution.get()
                if execution is not None:
                    execution.reserve_transport()
                response = await self._post_chat_completion(url, payload, headers)
                if response.status_code >= 400:
                    message = (
                        f"LLM request failed with {response.status_code}: "
                        f"{response.text.replace(provider.api_key, '[REDACTED]')[:500]}"
                    )
                    if response.status_code not in _RETRYABLE_STATUS_CODES:
                        raise LLMError(message)
                    raise _RetryableLLMError(message)
                return self._parse_text_response(response, provider)
            except _RetryableLLMError as exc:
                if attempt + 1 >= attempts:
                    raise LLMError(
                        f"LLM request failed after {attempts} attempts: {exc}"
                    ) from exc
                await self._sleep_before_retry(attempt)
        raise LLMError("LLM request failed before response.")

    async def _post_chat_completion(
        self,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                return await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise _RetryableLLMError(
                f"LLM request timed out after {self._settings.llm_timeout_seconds} seconds."
            ) from exc
        except httpx.HTTPError as exc:
            raise _RetryableLLMError(f"LLM request failed before response: {exc}") from exc

    async def _sleep_before_retry(self, attempt_index: int) -> None:
        backoff_seconds = max(0.0, self._settings.llm_retry_backoff_seconds)
        if backoff_seconds <= 0:
            return
        await asyncio.sleep(backoff_seconds * (2**attempt_index))

    def _parse_text_response(self, response: httpx.Response, provider: LLMProviderConfig) -> str:
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            preview = response.text.replace(provider.api_key, "[REDACTED]")[:500]
            raise _RetryableLLMError(
                f"LLM response was not valid JSON: {preview}"
            ) from exc
        usage = self._parse_usage(data.get("usage"))
        self._usage_context.set(usage)
        execution = current_llm_execution.get()
        if execution is not None and usage is not None:
            if usage.prompt_tokens is not None and usage.completion_tokens is not None:
                execution.settle_attempt(prompt_tokens=usage.prompt_tokens,
                                         completion_tokens=usage.completion_tokens,
                                         cache_hit_tokens=usage.prompt_cache_hit_tokens or 0)
                execution.provider_accounted = True
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response did not contain choices[0].message.content.") from exc
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        finish_reason = str(finish_reason) if finish_reason is not None else None
        self._response_context.set((provider.name, provider.model, finish_reason))
        if finish_reason == "length":
            raise _RetryableLLMError(
                "LLM response stopped because the output length limit was reached."
            )
        if not isinstance(content, str) or not content.strip():
            raise _RetryableLLMError("LLM returned empty content.")
        return content

    def consume_last_usage(self) -> LLMUsage | None:
        usage = self._usage_context.get()
        self._usage_context.set(None)
        return usage

    def last_provider(self) -> str | None:
        response = self._response_context.get()
        if response is not None:
            return response[0]
        if self._settings.has_primary_llm_credentials:
            return self._settings.llm_provider_name or "doubao"
        if self._settings.has_backup_llm_credentials:
            return "backup"
        return None

    def last_model(self) -> str | None:
        response = self._response_context.get()
        if response is not None:
            return response[1]
        return self._settings.ark_model or self._settings.backup_llm_model

    def last_finish_reason(self) -> str | None:
        response = self._response_context.get()
        if response is not None:
            return response[2]
        return None

    def last_route_decision(self) -> ModelRouteDecision | None:
        return self._last_route_decision

    def _provider_configs(self) -> list[LLMProviderConfig]:
        route = build_model_route_decision(self._settings)
        self._last_route_decision = route
        providers_by_kind: dict[ModelProviderKind, LLMProviderConfig] = {}
        if self._settings.ark_api_key and self._settings.ark_model:
            providers_by_kind["primary"] = (
                LLMProviderConfig(
                    name=self._settings.llm_provider_name or "doubao",
                    provider_kind="primary",
                    api_key=self._settings.ark_api_key,
                    base_url=self._settings.ark_base_url,
                    model=self._settings.ark_model,
                )
            )
        if self._settings.backup_llm_api_key and self._settings.backup_llm_model:
            providers_by_kind["backup"] = (
                LLMProviderConfig(
                    name="backup",
                    provider_kind="backup",
                    api_key=self._settings.backup_llm_api_key,
                    base_url=self._settings.backup_llm_base_url,
                    model=self._settings.backup_llm_model,
                )
            )
        if route.status == "blocked":
            return []
        providers: list[LLMProviderConfig] = []
        for candidate in (route.selected, route.fallback):
            if candidate is None:
                continue
            provider = providers_by_kind.get(candidate.provider_kind)
            if provider is not None and provider not in providers:
                providers.append(provider)
        for provider_kind in ("primary", "backup"):
            provider = providers_by_kind.get(provider_kind)
            if provider is not None and provider not in providers:
                providers.append(provider)
        return providers

    def _route_error_message(self) -> str:
        route = self._last_route_decision or build_model_route_decision(self._settings)
        if route.status == "blocked":
            reasons = "; ".join(route.blocked_reasons) or "model route policy blocked the request"
            return f"LLM model route blocked: {reasons}"
        return (
            "ARK_API_KEY and ARK_MODEL or BACKUP_LLM_API_KEY and BACKUP_LLM_MODEL "
            "are required for real execution mode."
        )

    def _parse_usage(self, usage: object) -> LLMUsage | None:
        if not isinstance(usage, dict):
            return None
        return LLMUsage(
            prompt_tokens=self._optional_int(usage.get("prompt_tokens")),
            completion_tokens=self._optional_int(usage.get("completion_tokens")),
            total_tokens=self._optional_int(usage.get("total_tokens")),
            prompt_cache_hit_tokens=self._optional_int(usage.get("prompt_cache_hit_tokens")),
            prompt_cache_miss_tokens=self._optional_int(usage.get("prompt_cache_miss_tokens")),
        )

    def _optional_int(self, value: object) -> int | None:
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    def _extract_json(self, content: str) -> dict[str, Any]:
        try:
            return extract_json_object(content)
        except JsonExtractionError as exc:
            raise LLMError(str(exc)) from exc
