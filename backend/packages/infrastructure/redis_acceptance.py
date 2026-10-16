"""Opt-in Redis server acceptance, to run on the deployment machine.

Preview is the default. Execution touches only two keys in a random namespace;
they expire after one second and one hour. No report or model is invoked.
"""

import argparse
import asyncio
import json
import os
from asyncio import sleep
from uuid import uuid4

from packages.infrastructure.redis_runtime import RedisRuntime


async def verify(url: str | None) -> dict:
    runtime = RedisRuntime(
        url=url, enabled=True, namespace=f"acceptance-{uuid4().hex}", timeout_seconds=2
    )
    try:
        if not await runtime.ping():
            raise RuntimeError("Redis ping failed")
        key = runtime.cache_key("ttl-probe")
        value = {"probe": "deployment-acceptance"}
        if not await runtime.set_json(key, value, ttl_seconds=1):
            raise RuntimeError("Redis cache write failed")
        if await runtime.get_json(key) != value:
            raise RuntimeError("Redis cache roundtrip failed")
        await sleep(1.2)
        if await runtime.get_json(key) is not None:
            raise RuntimeError("Redis TTL did not expire")
        results = await asyncio.gather(
            *(
                runtime.check_rate_limit("concurrent-probe", limit=10, window_seconds=3600)
                for _ in range(20)
            )
        )
        allowed = sum(result.allowed for result in results)
        denied = len(results) - allowed
        if allowed != 10 or any(
            not result.allowed and result.retry_after_seconds < 1 for result in results
        ):
            raise RuntimeError(
                "Redis atomic limit check failed; rerun if an hour boundary was crossed"
            )
        return {
            "executed": True,
            "ping": True,
            "cache_roundtrip": True,
            "ttl_expired": True,
            "allowed": allowed,
            "denied": denied,
        }
    finally:
        await runtime.aclose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            json.dumps(
                {
                    "executed": False,
                    "checks": [
                        "ping",
                        "cache roundtrip",
                        "1 second TTL",
                        "20 concurrent Lua calls / limit 10",
                    ],
                }
            )
        )
        return 0
    try:
        print(json.dumps(asyncio.run(verify(os.getenv("REDIS_URL")))))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "executed": True,
                    "passed": False,
                    "detail": (
                        "Redis acceptance failed; inspect service/configuration, "
                        "or retry at a stable hour window."
                    ),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
