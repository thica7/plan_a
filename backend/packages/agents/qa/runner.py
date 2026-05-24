from __future__ import annotations

from typing import Any, Literal


async def run_phase(service: Any, record: Any, phase: Literal["collect", "analyst"]) -> None:
    await service._real_phase_qa_step(record, phase)


async def run_final(service: Any, record: Any) -> None:
    await service._real_qa_step(record)
