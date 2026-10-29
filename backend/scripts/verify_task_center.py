"""Preview or explicitly execute the private local task-center acceptance suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            "preview: seed=4242; 2 API + 2 relay processes; concurrency=10,50,100; "
            "--execute creates a private PostgreSQL cluster and random loopback sockets"
        )
        return 0
    from scripts.task_center_acceptance import execute

    result = execute()
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
