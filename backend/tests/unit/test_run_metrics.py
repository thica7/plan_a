from packages.schema.models import RunMetrics


def test_run_metrics_exposes_enterprise_quality_fields() -> None:
    metrics = RunMetrics()

    assert metrics.schema_pass_rate == 1.0
    assert metrics.human_override_rate == 0.0
    assert metrics.acceptance_rate == 0.0
