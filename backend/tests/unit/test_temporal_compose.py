from pathlib import Path


def test_docker_compose_declares_temporal_server_ui_and_worker() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "temporalio/auto-setup:1.27.2" in compose
    assert "DB: postgres12" in compose
    assert "temporalio/ui:2.34.0" in compose
    assert "temporal-worker:" in compose
    assert "TEMPORAL_ADDRESS: temporal:7233" in compose
    assert 'command: ["python", "-m", "packages.workflows.worker"]' in compose
    assert '"127.0.0.1:7233:7233"' in compose
    assert '"127.0.0.1:8233:8080"' in compose


def test_makefile_declares_real_temporal_server_smoke() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "smoke-temporal-server:" in makefile
    assert "backend/scripts/smoke_temporal_server.py" in makefile


def test_phase4_readiness_gate_covers_enterprise_closeout_items() -> None:
    script = Path("backend/scripts/phase4_readiness_report.py").read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in script
    assert "source_registry_projection" in script
    assert "evidence_embedding_index" in script
    assert "workspace_member_bootstrap" in script
    assert "rbac_cross_workspace_block" in script
