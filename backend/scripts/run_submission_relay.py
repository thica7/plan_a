"""Bounded durable submission relay; preview never constructs runtime dependencies."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def serve(relay, stop, *, poll_seconds=0.25):
    async def worker():
        while not stop.is_set():
            result = await relay.run_once()
            if result.status == "idle":
                try:
                    await asyncio.wait_for(stop.wait(), poll_seconds)
                except TimeoutError:
                    pass

    # Stop intake first, then join every claimed dispatch before closing its pools.
    workers = [asyncio.create_task(worker()) for _ in range(relay.concurrency)]
    try:
        await asyncio.gather(*workers)
    finally:
        stop.set()
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


async def run(concurrency):
    from app import deps
    from packages.task_center.factory import close_task_services, get_task_service
    from packages.task_center.relay import OutboxRelay

    settings = deps.get_app_settings()
    if not settings.task_center_enabled:
        raise RuntimeError("TASK_CENTER_ENABLED must be true")
    store = await asyncio.to_thread(deps.get_enterprise_store)
    journal = await asyncio.to_thread(deps.get_run_journal)
    service = get_task_service(settings, store=store, journal=journal)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    try:
        await service.open()
        # Build the existing guarded runtime only for actual worker execution.
        run_service = deps.get_run_service()
        service.require_execution(run_service)
        workflow = deps.get_temporal_workflow_service()

        async def dispatch(claim):
            return await service.dispatch(claim, run_service=run_service, workflow_service=workflow)

        relay = OutboxRelay(
            service.repository,
            dispatch,
            concurrency=concurrency,
            lease_seconds=settings.task_center_dispatch_lease_seconds,
            max_attempts=settings.task_center_dispatch_max_attempts,
            retry_base_seconds=settings.task_center_dispatch_retry_seconds,
        )
        await serve(relay, stop)
    finally:
        stop.set()
        await deps.close_run_services()
        await close_task_services()
        if hasattr(store, "close"):
            await asyncio.to_thread(store.close)
        for name in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 65))
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            "preview: submission relay; --execute uses configured metadata, "
            "durable journal and execution control"
        )
        return 0
    from packages.task_center.errors import TaskCenterError

    try:
        asyncio.run(run(args.concurrency))
    except (TaskCenterError, RuntimeError):
        print("submission relay stopped: configuration or dependency unavailable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
