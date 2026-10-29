"""CLI preview never reads secrets; idle relays keep polling and drain on stop."""

import asyncio
import importlib
import os

import pytest


def test_migration_preview_does_not_read_owner_secret(monkeypatch, capsys):
    module = importlib.import_module("scripts.migrate_task_center")
    original = os.getenv

    def protected(name, *args):
        if name in {"TASK_CENTER_MIGRATION_DATABASE_URL", "TASK_CENTER_DATABASE_URL"}:
            pytest.fail("preview read a secret")
        return original(name, *args)

    monkeypatch.setattr(os, "getenv", protected)
    assert module.main([]) == 0
    result = capsys.readouterr().out
    assert "001_core" in result and "preview" in result.lower()


def test_relay_preview_does_not_construct_settings_or_execution(monkeypatch, capsys):
    module = importlib.import_module("scripts.run_submission_relay")
    import packages.config

    monkeypatch.setattr(
        packages.config, "get_settings", lambda: pytest.fail("preview constructed settings")
    )
    assert module.main([]) == 0
    assert "preview" in capsys.readouterr().out.lower()


async def test_relay_idle_polls_again_and_joins_inflight_before_return():
    module = importlib.import_module("scripts.run_submission_relay")
    stop, entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Relay:
        concurrency = 1
        calls = 0

        async def run_once(self):
            self.calls += 1
            if self.calls == 1:
                return type("Result", (), {"status": "idle"})()
            entered.set()
            await release.wait()
            return type("Result", (), {"status": "dispatched"})()

    relay = Relay()
    task = asyncio.create_task(module.serve(relay, stop, poll_seconds=0.01))
    await asyncio.wait_for(entered.wait(), 1)
    stop.set()
    await asyncio.sleep(0.01)
    assert not task.done()
    release.set()
    await task
    assert relay.calls == 2


@pytest.mark.parametrize("script", ["migrate_task_center.py", "run_submission_relay.py"])
def test_cli_can_preview_directly_outside_repository(script, tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    filename = Path(__file__).resolve().parents[2] / "scripts" / script
    result = subprocess.run(
        [sys.executable, str(filename)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": "", "COMPETISCOPE_LOAD_ENV_FILES": "0"},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert "preview" in result.stdout
