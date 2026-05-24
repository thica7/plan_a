from pathlib import Path
from uuid import uuid4

from app.events import RunEvent
from packages.memory import RunJournal
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


def test_run_journal_persists_run_and_events() -> None:
    db_path = Path("runs") / f"test-run-journal-{uuid4().hex}.db"
    journal = RunJournal(db_path)
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:01",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )
    event = RunEvent(
        id=1,
        run_id="run-1",
        type="run_completed",
        agent="orchestrator",
        message="done",
    )

    try:
        journal.save_run(detail)
        journal.append_event(event)

        loaded_runs = journal.load_runs()
        loaded_events = journal.load_events("run-1")

        assert loaded_runs[0].id == "run-1"
        assert loaded_events[0].type == "run_completed"
    finally:
        db_path.unlink(missing_ok=True)
