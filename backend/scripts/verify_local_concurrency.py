"""Preview or explicitly execute isolated, offline local concurrency acceptance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def request_count(value: str) -> int:
    count = int(value)
    if not 16 <= count <= 256:
        raise argparse.ArgumentTypeError("must be between 16 and 256")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run temporary offline acceptance")
    parser.add_argument("--requests", type=request_count, default=64)
    parser.add_argument("--output", type=Path, default=Path("local-concurrency-result.json"))
    options = parser.parse_args(argv)
    if not options.execute:
        print(json.dumps({
            "mode": "preview", "requests": options.requests, "seed": 20261028,
            "execution_control_enabled": True, "external_services": False,
            "processes": 2, "limits": {"running": 2, "workspace_running": 1,
                                      "model": 2, "queue": 8},
            "output": str(options.output), "writes": False,
            "next_step": "Add --execute to run only in a fresh temporary directory.",
        }, indent=2))
        return 0
    # Preview deliberately imports no application code, reads no .env, and creates no DB.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.local_concurrency_harness import execute

    result = execute(options.requests)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "output": str(options.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
