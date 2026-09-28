#!/usr/bin/env python3
"""Deploy Compose and display URLs from its resolved port mappings."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose_urls(config: dict) -> dict:
    urls = {}
    for service, label, target in (
        ("nginx", "App", 80),
        ("temporal-ui", "Temporal UI", 8080),
        ("qdrant", "Qdrant", 6333),
    ):
        for port in config["services"][service].get("ports", []):
            if int(port["target"]) != target:
                continue
            host = port.get("host_ip") or "127.0.0.1"
            if host in {"0.0.0.0", "::"}:
                host = "127.0.0.1"
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            urls[label] = f"http://{host}:{port['published']}"
    if "App" in urls:
        urls["API"] = f"{urls['App']}/api"
    return urls


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--no-detach", action="store_true")
    parser.add_argument("--urls-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not shutil.which("docker"):
            raise RuntimeError("Docker with Compose v2 is required")
        if not (ROOT / ".env").exists():
            shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
            print(
                "Created .env from .env.example; configure provider keys before real runs."
            )
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        urls = compose_urls(json.loads(result.stdout))
        if not args.urls_only:
            command = ["docker", "compose", "up"]
            if not args.no_detach:
                command += ["-d", "--wait", "--wait-timeout", "180"]
            if args.build:
                command.append("--build")
            for label, url in urls.items():
                print(f"{label}: {url}", flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
        else:
            for label, url in urls.items():
                print(f"{label}: {url}")
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"[plan_a] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
