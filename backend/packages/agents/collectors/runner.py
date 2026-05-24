from __future__ import annotations

from typing import Any


async def dispatch(service: Any, record: Any, dimensions: list[str], competitors: list[str]) -> None:
    await service._real_collector_dispatch_step(record, dimensions, competitors)


async def run_branch(service: Any, record: Any, dimension: str, competitor: str) -> None:
    await service._real_collector_branch_step(record, dimension, competitor)


async def join(service: Any, record: Any, dimensions: list[str]) -> None:
    await service._real_collect_join_step(record, dimensions)
