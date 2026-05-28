from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from packages.config import Settings
from packages.llm.json_extract import JsonExtractionError, extract_json_object


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class DoubaoClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_usage: LLMUsage | None = None

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: str,
    ) -> dict[str, Any]:
        content = await self.complete_text(
            system=(
                f"{system}\n\n"
                "Return only valid JSON. Do not wrap it in markdown fences. "
                f"The JSON shape is: {schema_hint}"
            ),
            user=user,
        )
        return self._extract_json(content)

    async def complete_text(self, *, system: str, user: str) -> str:
        if not self._settings.ark_api_key or not self._settings.ark_model:
            raise LLMError("ARK_API_KEY and ARK_MODEL are required for real execution mode.")
        self._last_usage = None

        payload = {
            "model": self._settings.ark_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._settings.llm_temperature,
        }
        headers = {"Authorization": f"Bearer {self._settings.ark_api_key}"}
        url = f"{self._settings.ark_base_url}/chat/completions"

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
