from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from webfetch_v2.batch import load_batch_items, run_batch
from webfetch_v2.cache import list_cache, load_cached_result, load_cached_result_by_url, write_cache
from webfetch_v2.doctor import run_doctor
from webfetch_v2.fetcher import fetch_url
from webfetch_v2.models import FetchMode
from webfetch_v2.session import open_auth_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webfetch-v2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="Fetch and extract a web page")
    fetch.add_argument("url")
    fetch.add_argument("--mode", choices=[mode.value for mode in FetchMode], default=FetchMode.AUTO.value)
    fetch.add_argument("--timeout", type=float, default=15.0)
    fetch.add_argument("--quality-threshold", type=float, default=0.55)
    fetch.add_argument("--profile", help="Authorized browser profile name. Use only with user approval.")
    fetch.add_argument("--artifact-dir", type=Path)
    fetch.add_argument("--screenshot", action="store_true")
    fetch.add_argument("--capture-network", action="store_true")
    fetch.add_argument("--cache", action="store_true", help="Persist result JSON/markdown/artifacts to the cache directory")
    fetch.add_argument("--prefer-cache", action="store_true", help="Return cached result for the URL when available")
    fetch.add_argument("--cache-dir", type=Path, help="Override cache root directory")
    fetch.add_argument("--pretty", action="store_true")


    batch = subparsers.add_parser("batch", help="Fetch a JSON/TXT list of URLs")
    batch.add_argument("input", type=Path)
    batch.add_argument("--mode", choices=[mode.value for mode in FetchMode], default=FetchMode.AUTO.value)
    batch.add_argument("--timeout", type=float, default=15.0)
    batch.add_argument("--quality-threshold", type=float, default=0.55)
    batch.add_argument("--cache", action="store_true")
    batch.add_argument("--prefer-cache", action="store_true")
    batch.add_argument("--cache-dir", type=Path)
    batch.add_argument("--artifact-dir", type=Path)
    batch.add_argument("--screenshot", action="store_true")
    batch.add_argument("--capture-network", action="store_true")
    batch.add_argument("--pretty", action="store_true")
    doctor = subparsers.add_parser("doctor", help="Check local webfetch_v2 environment")
    doctor.add_argument("--check-browser", action="store_true", help="Try launching Chromium if Playwright is installed")
    doctor.add_argument("--pretty", action="store_true")


    cache_parser = subparsers.add_parser("cache", help="Inspect cached evidence")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command", required=True)
    cache_list = cache_subparsers.add_parser("list", help="List cached fetch results")
    cache_list.add_argument("--cache-dir", type=Path)
    cache_list.add_argument("--pretty", action="store_true")
    cache_show = cache_subparsers.add_parser("show", help="Show a cached fetch result by key")
    cache_show.add_argument("key")
    cache_show.add_argument("--cache-dir", type=Path)
    cache_show.add_argument("--pretty", action="store_true")
    auth = subparsers.add_parser("auth-session", help="Open a headed browser for user-authorized session setup")
    auth.add_argument("--profile", required=True, help="Persistent profile name to create or reuse")
    auth.add_argument("--url", required=True, help="Login or landing URL to open")
    auth.add_argument("--timeout", type=float, default=0.0)
    auth.add_argument("--pretty", action="store_true")
    return parser


async def run_fetch(args: argparse.Namespace) -> int:
    if args.prefer_cache:
        cached = load_cached_result_by_url(args.url, cache_root=args.cache_dir)
        if cached is not None:
            _print_json(cached, pretty=args.pretty)
            return 0 if cached.get("ok") else 2

    artifact_dir = args.artifact_dir
    if args.cache and artifact_dir is None and args.mode == FetchMode.BROWSER.value:
        from webfetch_v2.paths import cache_dir

        artifact_dir = cache_dir() / "artifacts"

    result = await fetch_url(
        args.url,
        mode=args.mode,
        timeout_seconds=args.timeout,
        quality_threshold=args.quality_threshold,
        profile=args.profile,
        artifact_dir=artifact_dir,
        screenshot=args.screenshot,
        capture_network=args.capture_network,
    )
    payload = result.to_dict()
    if args.cache:
        payload["cache"] = write_cache(result, cache_root=args.cache_dir).to_dict()
    _print_json(payload, pretty=args.pretty)
    return 0 if result.ok else 2


async def run_batch_command(args: argparse.Namespace) -> int:
    items = load_batch_items(args.input)
    payload = await run_batch(
        items,
        mode=args.mode,
        timeout_seconds=args.timeout,
        quality_threshold=args.quality_threshold,
        cache=args.cache,
        prefer_cache=args.prefer_cache,
        cache_root=args.cache_dir,
        artifact_dir=args.artifact_dir,
        screenshot=args.screenshot,
        capture_network=args.capture_network,
    )
    _print_json(payload, pretty=args.pretty)
    return 0 if payload["summary"]["failed"] == 0 else 2

async def run_doctor_command(args: argparse.Namespace) -> int:
    result = await run_doctor(check_browser=args.check_browser)
    _print_json(result.to_dict(), pretty=args.pretty)
    return 0 if result.ok else 2


async def run_auth_session(args: argparse.Namespace) -> int:
    result = await open_auth_session(
        profile=args.profile,
        url=args.url,
        timeout_seconds=args.timeout,
    )
    _print_json(result.to_dict(), pretty=args.pretty)
    return 0 if result.ok else 2


def run_cache_command(args: argparse.Namespace) -> int:
    if args.cache_command == "list":
        _print_json({"entries": list_cache(cache_root=args.cache_dir)}, pretty=args.pretty)
        return 0
    if args.cache_command == "show":
        cached = load_cached_result(args.key, cache_root=args.cache_dir)
        if cached is None:
            _print_json({"ok": False, "error": "cache_entry_not_found", "key": args.key}, pretty=args.pretty)
            return 2
        _print_json(cached, pretty=args.pretty)
        return 0
    raise ValueError(f"unknown cache command: {args.cache_command}")

def _print_json(payload: dict, *, pretty: bool) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "fetch":
        return asyncio.run(run_fetch(args))
    if args.command == "doctor":
        return asyncio.run(run_doctor_command(args))
    if args.command == "batch":
        return asyncio.run(run_batch_command(args))
    if args.command == "auth-session":
        return asyncio.run(run_auth_session(args))
    if args.command == "cache":
        return run_cache_command(args)
    parser.error(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
