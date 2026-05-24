from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.tools import fetch_page


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="https://example.com")
    args = parser.parse_args()

    result = await fetch_page(args.url)
    print(
        json.dumps(
            {
                "component": "fetch",
                "ok": result.ok,
                "url": result.url,
                "status_code": result.status_code,
                "title": result.title,
                "content_hash": result.content_hash,
                "text_chars": len(result.text),
                "error": result.error,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
