from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings, get_settings
from packages.llm import DoubaoClient


async def main() -> None:
    settings = get_settings()
    if not settings.has_backup_llm_credentials:
        raise SystemExit("BACKUP_LLM_API_KEY and BACKUP_LLM_MODEL are required.")

    backup_only = Settings(
        demo_mode=False,
        ark_api_key=None,
        ark_model=None,
        ark_base_url=settings.ark_base_url,
        llm_timeout_seconds=settings.llm_timeout_seconds,
        llm_temperature=settings.llm_temperature,
        backup_llm_api_key=settings.backup_llm_api_key,
        backup_llm_base_url=settings.backup_llm_base_url,
        backup_llm_model=settings.backup_llm_model,
        pplx_api_key=settings.pplx_api_key,
        pplx_base_url=settings.pplx_base_url,
        web_search_provider=settings.web_search_provider,
        enterprise_store_backend=settings.enterprise_store_backend,
        enterprise_database_url=settings.enterprise_database_url,
    )
    client = DoubaoClient(backup_only)
    content = await client.complete_text(
        system="You are a smoke-test assistant. Keep the answer short.",
        user="Reply with exactly: ok",
    )
    print(
        json.dumps(
            {
                "component": "backup_llm",
                "ok": True,
                "provider": client.last_provider(),
                "model": client.last_model(),
                "response_chars": len(content),
                "preview": content[:80],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
