from __future__ import annotations

import json
import re
from typing import Any

import httpx

from packages.config import Settings


class LLMError(RuntimeError):
    pass


class DoubaoClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

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
            raise LLMError(f"LLM request timed out after {self._settings.llm_timeout_seconds} seconds.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed before response: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"LLM request failed with {response.status_code}: {response.text[:500]}")

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response did not contain choices[0].message.content.") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned empty content.")
        return content

    def _extract_json(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return self._loads_first_json_object(stripped)

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if fenced:
            return self._loads_first_json_object(fenced.group(1))

        first = stripped.find("{")
        if first >= 0:
            return self._loads_first_json_object(stripped[first:])

        raise LLMError("LLM response did not contain a JSON object.")

    def _loads_first_json_object(self, content: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(content.strip())
        if not isinstance(parsed, dict):
            raise LLMError("LLM response JSON root was not an object.")
        return parsed
