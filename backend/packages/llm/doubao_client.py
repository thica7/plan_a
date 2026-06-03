from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from packages.config import Settings
from packages.governance import build_model_route_decision
from packages.llm.json_extract import JsonExtractionError, extract_json_object
from packages.schema.enterprise import ModelProviderKind, ModelRouteDecision


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


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
        self._last_usage: LLMUsage | None = None
        self._last_provider: str | None = None
        self._last_model: str | None = None
        self._last_route_decision: ModelRouteDecision | None = None

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: str,
    ) -> dict[str, Any]:
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
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                self._last_usage = None
                self._last_provider = None
                self._last_model = None
        raise LLMError("LLM JSON request failed for all providers: " + " | ".join(errors))

    async def complete_text(self, *, system: str, user: str) -> str:
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
            except LLMError as exc:
                errors.append(f"{provider.name}: {exc}")
                self._last_usage = None
                self._last_provider = None
                self._last_model = None
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
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "X-Title": "Competiscope",
        }
        url = f"{provider.base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"LLM request timed out after {self._settings.llm_timeout_seconds} seconds."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed before response: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"LLM request failed with {response.status_code}: {response.text[:500]}")

        data = response.json()
        self._last_usage = self._parse_usage(data.get("usage"))
        self._last_provider = provider.name
        self._last_model = provider.model
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response did not contain choices[0].message.content.") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned empty content.")
        return content

    def consume_last_usage(self) -> LLMUsage | None:
        usage = self._last_usage
        self._last_usage = None
        return usage

    def last_provider(self) -> str | None:
        if self._last_provider:
            return self._last_provider
        if self._settings.has_primary_llm_credentials:
            return "doubao"
        if self._settings.has_backup_llm_credentials:
            return "backup"
        return None

    def last_model(self) -> str | None:
        return self._last_model or self._settings.ark_model or self._settings.backup_llm_model

    def last_route_decision(self) -> ModelRouteDecision | None:
        return self._last_route_decision

    def _provider_configs(self) -> list[LLMProviderConfig]:
        route = build_model_route_decision(self._settings)
        self._last_route_decision = route
        providers_by_kind: dict[ModelProviderKind, LLMProviderConfig] = {}
        if self._settings.ark_api_key and self._settings.ark_model:
            providers_by_kind["primary"] = (
                LLMProviderConfig(
                    name="doubao",
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
        )

    def _optional_int(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_json(self, content: str) -> dict[str, Any]:
        try:
            return extract_json_object(content)
        except JsonExtractionError as exc:
            raise LLMError(str(exc)) from exc
