"""One explicit task-center pool per process/event loop and trusted dependency set."""

from __future__ import annotations

import asyncio
import os

from .database import TaskCenterDatabase
from .errors import TaskCenterConfigurationError
from .repository import SubmissionRepository

_services: dict[tuple, object] = {}


def get_task_service(settings, *, store, journal):
    if not settings.task_center_enabled:
        return None
    if store is None or journal is None or str(journal.db_path) == ":memory:":
        raise TaskCenterConfigurationError(
            "Task center requires trusted metadata and a durable journal"
        )
    from .service import TaskCenterService

    key = (os.getpid(), id(asyncio.get_running_loop()), id(settings), id(store), id(journal))
    service = _services.get(key)
    if service is None:
        service = TaskCenterService(
            SubmissionRepository(TaskCenterDatabase(settings)),
            settings=settings,
            store=store,
            journal=journal,
        )
        _services[key] = service
    return service


async def stop_task_services() -> None:
    loop = id(asyncio.get_running_loop())
    services = [service for key, service in _services.items() if key[:2] == (os.getpid(), loop)]
    for service in services:
        service.stop_intake()
    for service in services:
        await service.drain()


async def close_task_services() -> None:
    await stop_task_services()
    loop = id(asyncio.get_running_loop())
    keys = [key for key in _services if key[:2] == (os.getpid(), loop)]
    for key in keys:
        await _services.pop(key).close()
