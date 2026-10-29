"""Bounded delivery; dispatch acceptance never implies graph completion.

A timed out/cancelled sender may have been accepted remotely. All such outcomes
retain their reservation and replay the same business idempotency key. A receiver
must durably enforce that identity. Process death is recovered by lease expiry.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

from .dispatch import Dispatcher
from .errors import DispatchConflict, InvalidTaskCenterRequest, TaskCenterError
from .models import DispatchClaim
from .repository import SubmissionRepository


@dataclass(frozen=True)
class RelayResult:
    status: str
    submission_id: str | None = None


class OutboxRelay:
    def __init__(
        self,
        repository: SubmissionRepository,
        dispatcher: Dispatcher,
        *,
        lease_seconds: float = 30,
        dispatch_timeout_seconds: float | None = None,
        max_attempts: int = 3,
        retry_base_seconds: float = 1,
        concurrency: int = 4,
    ) -> None:
        if type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds):
            raise InvalidTaskCenterRequest("invalid outbox relay settings")
        timeout = (
            lease_seconds * 0.8 if dispatch_timeout_seconds is None else dispatch_timeout_seconds
        )
        if (
            not all(
                type(v) in (int, float) and math.isfinite(v)
                for v in (lease_seconds, timeout, retry_base_seconds)
            )
            or lease_seconds <= 0
            or not 0 < timeout < lease_seconds
            or not 0 <= retry_base_seconds <= 300
            or type(max_attempts) is not int
            or max_attempts < 1
            or type(concurrency) is not int
            or not 1 <= concurrency <= 64
        ):
            raise InvalidTaskCenterRequest("invalid outbox relay settings")
        self.repository = repository
        self.dispatcher = dispatcher
        self.lease_seconds = lease_seconds
        self.dispatch_timeout_seconds = timeout
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.concurrency = concurrency
        self._slots = asyncio.Semaphore(concurrency)

    async def _failed(self, claim: DispatchClaim, code: str) -> RelayResult:
        accepted = await self.repository.fail(
            claim,
            error_code=code,
            unknown=True,
            max_attempts=self.max_attempts,
            retry_delay_seconds=min(
                300, self.retry_base_seconds * (2 ** min(claim.attempt_count - 1, 16))
            ),
        )
        status = "failed" if claim.attempt_count >= self.max_attempts else "retry_scheduled"
        return RelayResult(status if accepted else "lease_lost", claim.submission_id)

    async def _deliver(self, claim: DispatchClaim, deadline: float) -> RelayResult:
        if not await self.repository.mark_sending(claim):
            return RelayResult("lease_lost", claim.submission_id)
        # Start the monotonic budget before claim IO, so this deadline is
        # conservative even when the database and application wall clocks differ.
        # Every durable transition independently checks actual DB lease time.
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return await self._failed(claim, "dispatch_timeout")
        try:
            async with asyncio.timeout(min(self.dispatch_timeout_seconds, remaining * 0.8)):
                receipt = await self.dispatcher(claim)
        except TimeoutError:
            return await self._failed(claim, "dispatch_timeout")
        except Exception:
            return await self._failed(claim, "dispatch_error")
        try:
            accepted = await self.repository.acknowledge(claim, receipt)
        except DispatchConflict:
            return await self._failed(claim, "receipt_mismatch")
        return RelayResult("dispatched" if accepted else "lease_lost", claim.submission_id)

    async def run_once(self, *, submission_id: str | None = None) -> RelayResult:
        async with self._slots:
            deadline = asyncio.get_running_loop().time() + self.lease_seconds
            claim = await self.repository.claim(
                submission_id=submission_id,
                lease_seconds=self.lease_seconds,
                max_attempts=self.max_attempts,
            )
            if claim is None:
                return RelayResult("idle")
            try:
                return await self._deliver(claim, deadline)
            except asyncio.CancelledError:
                # Finish the short bookkeeping transaction even if the caller
                # cancels repeatedly. Database timeouts bound its lock/IO waits.
                cleanup = asyncio.create_task(self._failed(claim, "dispatch_cancelled"))
                try:
                    while not cleanup.done():
                        try:
                            await asyncio.shield(cleanup)
                        except asyncio.CancelledError:
                            continue
                    cleanup.result()
                except TaskCenterError:
                    # A rolled-back cleanup leaves the durable lease for expiry
                    # recovery. Preserve the caller's original cancellation.
                    pass
                raise
