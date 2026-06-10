import sqlite3

from app.events import RunEvent
from packages.memory import RunJournal
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


def test_run_journal_persists_run_and_events() -> None:
    journal = RunJournal.in_memory()
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

    journal.save_run(detail)
    journal.append_event(event)

    loaded_runs = journal.load_runs()
    loaded_run = journal.load_run("run-1")
    loaded_events = journal.load_events("run-1")

    assert loaded_runs[0].id == "run-1"
    assert loaded_run is not None
    assert loaded_run.id == "run-1"
    assert journal.load_run("missing") is None
    assert loaded_events[0].type == "run_completed"


def test_run_journal_summaries_do_not_require_full_detail_json(tmp_path) -> None:
    journal_path = tmp_path / "run_journal.db"
    journal = RunJournal(journal_path)
    detail = RunDetail(
        id="run-heavy",
        idempotency_key="ui-run:heavy",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="Heavy Run",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:01",
        plan=AnalysisPlan(topic="Heavy Run", competitors=["A"], dimensions=["pricing"]),
        report_md="x" * 1000,
    )

    journal.save_run(detail)
    with sqlite3.connect(journal_path) as conn:
        conn.execute("update runs set detail_json = ? where id = ?", ("not-json", detail.id))
        conn.commit()

    summaries = journal.load_run_summaries()

    assert [(item.id, item.topic, item.status) for item in summaries] == [
        ("run-heavy", "Heavy Run", "running")
    ]
    assert journal.run_exists("run-heavy") is True
    assert journal.run_exists("missing") is False


def test_run_journal_summaries_sort_by_updated_at_desc() -> None:
    journal = RunJournal.in_memory()
    old_created_recently = RunDetail(
        id="run-created-recently",
        topic="Created Recently",
        status="completed",
        execution_mode="real",
        created_at="2026-05-23T10:00:00",
        updated_at="2026-05-23T10:00:01",
        plan=AnalysisPlan(topic="Created Recently", competitors=["A"], dimensions=["pricing"]),
    )
    old_created_updated_later = RunDetail(
        id="run-updated-later",
        topic="Updated Later",
        status="interrupted",
        execution_mode="real",
        created_at="2026-05-23T09:00:00",
        updated_at="2026-05-23T11:00:00",
        plan=AnalysisPlan(topic="Updated Later", competitors=["A"], dimensions=["pricing"]),
    )

    journal.save_run(old_created_recently)
    journal.save_run(old_created_updated_later)

    summaries = journal.load_run_summaries()

    assert [summary.id for summary in summaries] == ["run-updated-later", "run-created-recently"]


def test_run_journal_reconciles_stale_summary_columns_from_detail_json(tmp_path) -> None:
    journal_path = tmp_path / "run_journal.db"
    journal = RunJournal(journal_path)
    detail = RunDetail(
        id="run-reconcile",
        idempotency_key="ui-run:reconcile",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="Reconcile Run",
        status="completed_with_blockers",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:01",
        plan=AnalysisPlan(topic="Reconcile Run", competitors=["A"], dimensions=["pricing"]),
    )
    journal.save_run(detail)
    with sqlite3.connect(journal_path) as conn:
        conn.execute(
            """
            update runs
            set status = 'queued', execution_mode = 'demo', topic = 'Wrong'
            where id = ?
            """,
            (detail.id,),
        )
        conn.execute(
            """
            update meta
            set value = '2'
            where key = 'run_summary_schema_version'
            """
        )
        conn.commit()

    reloaded = RunJournal(journal_path)
    summary = reloaded.load_run_summary(detail.id)

    assert summary is not None
    assert summary.status == "completed_with_blockers"
    assert summary.execution_mode == "real"
    assert summary.topic == "Reconcile Run"
