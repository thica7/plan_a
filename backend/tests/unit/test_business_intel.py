from packages.agents.executor import AgentExecutionRequest
from packages.business_intel import (
    analyze_evidence_gaps,
    analyze_red_team,
    build_business_intel_plan,
    build_evidence_gap_agent,
    build_red_team_agent,
    business_findings_to_redo_scopes,
    evaluate_business_qa,
    evaluate_report_release_gate,
    generate_dynamic_scenario_pack,
    list_business_qa_rules,
    list_scenario_packs,
    score_competitors,
    score_project_readiness,
    validate_project_claims,
)
from packages.business_intel.homepage import verify_homepage
from packages.business_intel.layers import assess_competitor_layer
from packages.schema.enterprise import (
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
    ProjectRecord,
    ReportVersionRecord,
)


def test_layer_assessment_prefers_direct_for_focused_pricing_comparison() -> None:
    assessment = assess_competitor_layer(
        topic="Cursor vs Copilot pricing battlecard",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing", "feature"],
    )

    assert assessment.layer == "L1"
    assert assessment.confidence >= 0.55
    assert "pricing_dimension" in assessment.signals


def test_layer_assessment_detects_market_landscape() -> None:
    assessment = assess_competitor_layer(
        topic="AI coding assistant market landscape",
        competitors=["Cursor", "Copilot", "Windsurf", "Tabnine", "Codeium"],
        dimensions=["market", "persona"],
    )

    assert assessment.layer == "L3"
    assert "many_competitors" in assessment.signals


def test_business_plan_selects_scenario_and_rules() -> None:
    plan = build_business_intel_plan(
        topic="Enterprise AI assistant security review",
        competitors=["A", "B"],
        dimensions=["security"],
    )

    assert plan.competitor_layer.layer in {"L1", "L2"}
    assert plan.scenario_pack.id == "enterprise_risk_review"
    assert "security" in plan.recommended_dimensions
    assert {rule.id for rule in plan.qa_rules} >= {
        "coverage_min_verified",
        "security_official_source",
    }


def test_scenario_pack_catalog_and_qa_rules_are_loaded() -> None:
    packs = list_scenario_packs()
    rules = list_business_qa_rules()

    assert len(packs) >= 5
    assert len(rules) == 8
    assert any(pack.id == "l1_direct_battlecard" for pack in packs)
    assert any(rule.id == "claim_has_evidence" for rule in rules)
    assert any(rule.id == "homepage_verified" for rule in rules)


def test_dynamic_scenario_pack_and_homepage_gate_are_deterministic() -> None:
    pack = generate_dynamic_scenario_pack(
        topic="AI meeting assistant landscape",
        competitors=["Fathom", "Otter", "Fireflies", "Avoma"],
        dimensions=["market"],
    )
    good = verify_homepage("Cursor")
    phantom = verify_homepage("FAKE_PRODUCT_NOT_EXISTS")

    assert pack.is_dynamic is True
    assert pack.competitor_layer == "L3"
    assert "market" in pack.required_dimensions
    assert good.verified is True
    assert phantom.verified is False
    assert phantom.reason == "phantom_name"


def test_business_qa_evaluator_passes_verified_pricing_pack() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    readiness = score_project_readiness(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert evaluation.finding_count == 0
    assert gaps.gap_count == 0
    assert evaluation.passed_rules == evaluation.total_rules
    assert readiness.risk_level == "ready"
    assert readiness.score >= 85
    assert readiness.recommendations[0].action_type == "approve_report"


def test_report_release_gate_requires_clean_qa_and_verified_evidence() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        report_md="Cursor publishes pricing. [source:evidence-1]",
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
    )
    project = ProjectRecord(
        id="project-1",
        workspace_id="workspace-1",
        name="Cursor pricing",
        topic="Cursor vs Copilot pricing comparison",
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        scenario_id="l1_pricing_pack",
    )

    passing = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    blocked = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=[evidence[0].model_copy(update={"quality_label": "stale"})],
        claims=claims,
    )

    assert passing.allowed is True
    assert passing.status == "pass"
    assert blocked.allowed is False
    assert blocked.status == "blocked"
    assert {issue.rule_id for issue in blocked.issues} >= {
        "business_qa_clean_required",
        "verified_evidence_rate",
    }


def test_claim_validator_cross_checks_evidence_support() -> None:
    competitor = _competitor()
    accepted = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-1",
        competitor_id=competitor.id,
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.sh/pricing",
        snippet="Cursor publishes pricing tiers for teams.",
        content_hash="hash-1",
        reliability_score=0.9,
        quality_label="accepted",
    )
    stale = accepted.model_copy(
        update={"id": "evidence-stale", "quality_label": "stale", "content_hash": "hash-stale"}
    )
    claims = [
        ClaimRecord(
            id="claim-supported",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing tiers.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        ),
        ClaimRecord(
            id="claim-blocked",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor has unpublished discounts.",
            evidence_ids=["evidence-stale"],
            confidence=0.9,
        ),
        ClaimRecord(
            id="claim-weak",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="feature",
            claim_text="Cursor dominates enterprise procurement.",
            evidence_ids=["evidence-1"],
            confidence=0.4,
        ),
    ]

    report = validate_project_claims(
        project_id="project-1",
        claims=claims,
        evidence=[accepted, stale],
    )

    statuses = {item.claim_id: item.status for item in report.results}
    assert statuses["claim-supported"] == "supported"
    assert statuses["claim-blocked"] == "blocked"
    assert statuses["claim-weak"] in {"weak", "unsupported"}
    assert report.blocker_count == 1
    assert report.warn_count >= 1


def test_report_release_gate_blocks_unresolved_run_qa_metadata() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        quality_metadata={
            "run_qa_findings": [
                {
                    "id": "qa-1",
                    "severity": "warn",
                    "problem": "No granular pricing comparison.",
                }
            ]
        }
    )
    project = _project()

    gate = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "run_qa_findings_unresolved" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_strong_conclusion_from_search_only_source() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="web_search_result",
            title="Cursor pricing search result",
            url="https://example.com/pricing",
            snippet="Search result summary.",
            content_hash="hash-1",
            reliability_score=0.68,
            quality_label="unreviewed",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor is the pricing winner.",
            evidence_ids=["evidence-1"],
            confidence=0.68,
        )
    ]
    report = _report_version(
        report_md="## Executive Summary\nCursor is the pricing winner. [source:pricing-1]",
        evidence_ids=["evidence-1"],
    )
    project = _project()

    gate = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert {
        "claim_uses_low_confidence_evidence",
        "strong_conclusion_uses_weak_source",
    } <= {issue.rule_id for issue in gate.issues}


def test_business_qa_evaluator_flags_stale_evidence_and_broken_claim_links() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="stale",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["missing-evidence"],
            confidence=0.9,
        )
    ]

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    readiness = score_project_readiness(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert evaluation.finding_count >= 2
    assert evaluation.blocker_count >= 1
    assert {finding.rule_id for finding in evaluation.findings} >= {
        "claim_has_evidence",
        "pricing_currentness",
    }
    assert gaps.gap_count >= 2
    assert {gap.gap_type for gap in gaps.gaps} >= {
        "claim_without_usable_evidence",
        "missing_dimension_coverage",
    }
    assert readiness.risk_level == "blocked"
    assert readiness.score < 85
    assert readiness.recommendations[0].priority == "critical"


def test_business_qa_rules_cover_five_redo_scope_routes() -> None:
    plan = build_business_intel_plan(
        topic="Enterprise AI assistant security review",
        competitors=["A", "B"],
        dimensions=["security", "feature"],
        requested_scenario_id="dynamic_enterprise",
    )
    competitors = [
        CompetitorRecord(
            id="competitor-a",
            workspace_id="workspace-1",
            name="A",
            normalized_name="a",
            layer="L2",
            metadata={"homepage_verified": False},
        ),
        CompetitorRecord(
            id="competitor-b",
            workspace_id="workspace-1",
            name="B",
            normalized_name="b",
            layer="L2",
            metadata={"homepage_verified": False},
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence-low",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="source-low",
            competitor_id="competitor-a",
            dimension="security",
            source_type="webpage_verified",
            title="Low confidence security note",
            snippet="Security claim.",
            content_hash="hash-low",
            reliability_score=0.2,
            quality_label="unreviewed",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-broken",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-a",
            claim_type="security",
            claim_text="A supports enterprise security controls.",
            evidence_ids=["missing-evidence"],
            confidence=0.6,
        )
    ]

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    synthetic_findings = [
        *evaluation.findings,
        evaluation.findings[0].model_copy(update={"rule_id": "cross_competitor_matrix"}),
        evaluation.findings[0].model_copy(update={"rule_id": "security_official_source"}),
        evaluation.findings[0].model_copy(update={"rule_id": "landscape_breadth"}),
    ]
    scopes = business_findings_to_redo_scopes(synthetic_findings)

    assert {scope.kind for scope in scopes} >= {
        "collector",
        "writer_only",
        "comparator",
        "analyst",
        "full",
    }


def test_phase3_red_team_and_evidence_gap_agents_hit_exit_criteria() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitors = [
        _competitor(),
        CompetitorRecord(
            id="competitor-copilot",
            workspace_id="workspace-1",
            name="Copilot",
            normalized_name="copilot",
            layer="L1",
            metadata={"homepage_verified": False},
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence-stale",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id="competitor-cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor pricing.",
            content_hash="hash-1",
            reliability_score=0.2,
            quality_label="stale",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-unsupported",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-cursor",
            claim_type="pricing",
            claim_text="Cursor pricing is better.",
            evidence_ids=["missing-evidence"],
            confidence=0.4,
        )
    ]
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    red_team = analyze_red_team(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        report_versions=[],
    )

    assert gaps.framework == "pydantic-ai"
    assert gaps.gap_count >= 1
    assert any(gap.competitor_id == "competitor-copilot" for gap in gaps.gaps)
    assert red_team.framework == "pydantic-ai"
    assert red_team.high_severity_count >= 2


async def test_phase3_pydantic_ai_executors_return_structured_outputs() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitor = _competitor()
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=[],
        claims=[],
    )

    gap_result = await build_evidence_gap_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="evidence_gap",
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [competitor.model_dump(mode="json")],
                "evidence": [],
                "claims": [],
            },
        )
    )
    red_team_result = await build_red_team_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="red_team",
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [competitor.model_dump(mode="json")],
                "evidence": [],
                "claims": [],
                "report_versions": [],
            },
        )
    )

    assert gap_result.status == "ok"
    assert gap_result.metadata["framework"] == "pydantic-ai"
    assert gap_result.metadata["execution_mode"] == "deterministic_handler"
    assert gap_result.metadata["typed_contract_enforced"] is True
    assert gap_result.metadata["input_schema_hash"]
    assert gap_result.metadata["output_schema_hash"]
    assert gap_result.metadata["pydantic_ai_runtime_agent_created"] is True
    assert gap_result.metadata["pydantic_ai_runtime_agent_class"] == "Agent"
    assert gap_result.metadata["pydantic_ai_model_backed_capable"] is True
    assert gap_result.metadata["pydantic_ai_model_backed_requested"] is False
    assert gap_result.payload["gap_count"] >= 1
    assert red_team_result.status == "ok"
    assert red_team_result.metadata["framework"] == "pydantic-ai"
    assert red_team_result.metadata["execution_mode"] == "deterministic_handler"
    assert red_team_result.metadata["typed_contract_enforced"] is True
    assert red_team_result.metadata["input_schema_hash"]
    assert red_team_result.metadata["output_schema_hash"]
    assert red_team_result.metadata["pydantic_ai_runtime_agent_created"] is True
    assert red_team_result.metadata["pydantic_ai_runtime_agent_class"] == "Agent"
    assert red_team_result.metadata["pydantic_ai_model_backed_capable"] is True
    assert red_team_result.metadata["pydantic_ai_model_backed_requested"] is False
    assert red_team_result.payload["high_severity_count"] >= 1


async def test_pydantic_ai_agent_can_execute_through_test_model_runtime() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[_competitor()],
        evidence=[],
        claims=[],
    )

    result = await build_evidence_gap_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="evidence_gap",
            context={"pydantic_ai_execution_mode": "test_model"},
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [_competitor().model_dump(mode="json")],
                "evidence": [],
                "claims": [],
            },
        )
    )

    assert result.status == "ok"
    assert result.metadata["execution_mode"] == "pydantic_ai_test_model_backed"
    assert result.metadata["pydantic_ai_model_backed_requested"] is True
    assert result.metadata["pydantic_ai_runtime_result_type"] == "AgentRunResult"
    assert result.payload["gap_count"] >= 1


def test_phase3_competitor_scores_return_ranked_scorecards() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitors = [
        _competitor(),
        CompetitorRecord(
            id="competitor-copilot",
            workspace_id="workspace-1",
            name="Copilot",
            normalized_name="copilot",
            layer="L1",
            metadata={"homepage_verified": True},
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence-cursor",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id="competitor-cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-cursor",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-cursor",
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-cursor"],
            confidence=0.9,
        )
    ]

    report = score_competitors(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )

    assert report.scores[0].competitor_id == "competitor-cursor"
    assert report.scores[0].total_score > report.scores[1].total_score
    assert report.scores[0].dimension_scores[0].dimension == "pricing"


def _competitor() -> CompetitorRecord:
    return CompetitorRecord(
        id="competitor-cursor",
        workspace_id="workspace-1",
        name="Cursor",
        normalized_name="cursor",
        layer="L1",
        metadata={"homepage_verified": True},
    )


def _project() -> ProjectRecord:
    return ProjectRecord(
        id="project-1",
        workspace_id="workspace-1",
        name="Cursor pricing",
        topic="Cursor vs Copilot pricing comparison",
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        scenario_id="l1_pricing_pack",
    )


def _report_version(
    *,
    report_md: str = "Cursor publishes pricing. [source:evidence-1]",
    evidence_ids: list[str] | None = None,
    quality_metadata: dict[str, object] | None = None,
) -> ReportVersionRecord:
    return ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        report_md=report_md,
        claim_ids=["claim-1"],
        evidence_ids=evidence_ids or ["evidence-1"],
        quality_metadata=quality_metadata or {},
    )
