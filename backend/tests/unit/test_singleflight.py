"""Bounded, event-loop-local sharing of one in-process computation."""

import asyncio
import importlib
import threading

import pytest


def flight_type():
    try:
        return importlib.import_module("packages.infrastructure.singleflight")
    except ModuleNotFoundError:
        pytest.fail("bounded singleflight has not been implemented")


@pytest.mark.asyncio
async def test_burst_runs_once_and_returns_independent_nested_copies():
    flight = flight_type().SingleFlight()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def work():
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"items": [[1]]}

    tasks = [asyncio.create_task(flight.do("same", work)) for _ in range(32)]
    await entered.wait()
    await asyncio.sleep(0)
    release.set()
    values = await asyncio.gather(*tasks)
    assert calls == 1
    values[0]["items"][0].append(2)
    assert all(value == {"items": [[1]]} for value in values[1:])


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_peer_and_exception_can_retry():
    flight = flight_type().SingleFlight()
    entered, release = asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        await release.wait()
        return [1]

    first = asyncio.create_task(flight.do("same", work))
    second = asyncio.create_task(flight.do("same", work))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == [1]

    async def broken():
        raise ValueError("synthetic failure")

    with pytest.raises(ValueError, match="synthetic"):
        await flight.do("same", broken)
    assert await flight.do("same", work) == [1]


@pytest.mark.asyncio
async def test_capacity_rejects_excess_keys_and_waiters_and_all_cancel_stops_work():
    module = flight_type()
    flight = module.SingleFlight(max_keys=1, max_waiters_per_key=2)
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    first = asyncio.create_task(flight.do("same", work))
    second = asyncio.create_task(flight.do("same", work))
    await entered.wait()
    with pytest.raises(module.SingleFlightCapacityError, match="waiter"):
        await flight.do("same", work)
    with pytest.raises(module.SingleFlightCapacityError, match="key"):
        await flight.do("other", work)
    first.cancel()
    second.cancel()
    await asyncio.gather(first, second, return_exceptions=True)
    await asyncio.wait_for(stopped.wait(), 1)
    await asyncio.sleep(0)
    assert await flight.do("other", lambda: asyncio.sleep(0, result=3)) == 3


def test_one_instance_can_be_reused_by_separate_event_loops():
    flight = flight_type().SingleFlight(max_keys=1)

    async def run(value):
        return await flight.do("same", lambda: asyncio.sleep(0, result=value))

    assert asyncio.run(run(1)) == 1
    assert asyncio.run(run(2)) == 2


@pytest.mark.asyncio
async def test_cancelled_local_thread_keeps_key_draining_until_real_computation_exits():
    from packages.knowledge.runtime import call_provider

    module = flight_type()
    flight = module.SingleFlight(max_keys=1)
    entered, release = threading.Event(), threading.Event()

    class Provider:
        requested_provider = "local-test"
        calls = 0

        def compute(self):
            self.calls += 1
            entered.set()
            release.wait(3)
            return [1]

    provider = Provider()
    first = asyncio.create_task(flight.do("same", lambda: call_provider(provider.compute)))
    try:
        while not entered.is_set():
            await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.sleep(0)
        with pytest.raises(module.SingleFlightCapacityError, match="draining"):
            await flight.do("same", lambda: call_provider(provider.compute))
        with pytest.raises(module.SingleFlightCapacityError, match="key"):
            await flight.do("other", lambda: asyncio.sleep(0))
        assert provider.calls == 1
    finally:
        release.set()
    for _ in range(100):
        await asyncio.sleep(.001)
        try:
            assert await flight.do("other", lambda: asyncio.sleep(0, result=2)) == 2
            break
        except module.SingleFlightCapacityError:
            continue
    else:
        pytest.fail("drained thread did not release capacity")


@pytest.mark.asyncio
async def test_local_thread_dispatch_preserves_context_variables():
    from contextvars import ContextVar

    from packages.knowledge.runtime import call_provider

    request_scope = ContextVar("offline-scope", default="missing")

    class Provider:
        requested_provider = "local-test"

        def compute(self):
            return request_scope.get()

    token = request_scope.set("workspace-test")
    try:
        assert await call_provider(Provider().compute) == "workspace-test"
    finally:
        request_scope.reset(token)
