from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import get_settings
from packages.search import PerplexitySearchClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="AI coding assistant competitors")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.has_web_search_credentials:
        raise SystemExit("PPLX_API_KEY is required for the Perplexity search smoke test.")

    results = await PerplexitySearchClient(settings).search(args.query, max_results=args.max_results)
    print(
        json.dumps(
            {
                "component": "search",
                "ok": bool(results),
                "provider": settings.web_search_provider,
                "result_count": len(results),
                "results": [result.__dict__ for result in results],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
