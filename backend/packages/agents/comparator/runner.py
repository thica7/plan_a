from __future__ import annotations

from typing import Any


async def run(service: Any, record: Any) -> None:
    await service._real_comparator_step(record)
