from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import get_settings
from packages.llm import DoubaoClient


async def main() -> None:
    settings = get_settings()
    if not settings.has_llm_credentials:
        raise SystemExit("ARK_API_KEY and ARK_MODEL are required for the LLM smoke test.")

    content = await DoubaoClient(settings).complete_text(
        system="You are a smoke-test assistant. Keep the answer short.",
        user="Reply with exactly: ok",
    )
    print(
        json.dumps(
            {
                "component": "llm",
                "ok": True,
                "model": settings.ark_model,
                "response_chars": len(content),
                "preview": content[:80],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
