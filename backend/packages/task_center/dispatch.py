"""Trusted dispatch boundary. A receipt confirms acceptance, not graph completion."""

from dataclasses import dataclass
from typing import Protocol

from .models import DispatchClaim


@dataclass(frozen=True)
class DispatchReceipt:
    run_id: str
    workflow_id: str | None = None


class Dispatcher(Protocol):
    async def __call__(self, claim: DispatchClaim) -> DispatchReceipt: ...
