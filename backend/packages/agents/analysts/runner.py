from __future__ import annotations

from typing import Any


async def dispatch(
    service: Any, record: Any, dimensions: list[str], competitors: list[str]
) -> None:
    await service._real_analyst_dispatch_step(record, dimensions, competitors)


async def run_branch(
    service: Any,
    record: Any,
    dimension: str,
    competitor: str,
    *,
    expected_snapshot_id: str | None = None,
) -> None:
    await service._real_analyst_branch_step(
        record, dimension, competitor, expected_snapshot_id=expected_snapshot_id
    )


async def join(service: Any, record: Any, dimensions: list[str], competitors: list[str]) -> None:
    await service._real_analyst_join_step(record, dimensions, competitors)
