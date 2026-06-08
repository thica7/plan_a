from packages.enterprise import (
    EnterpriseMemoryStore,
    build_advisory_context_report,
)
from packages.memory import PreferenceMemoryStore
from packages.schema.enterprise import EvidenceRecord, MemoryCandidate, ReportVersionRecord


def test_advisory_context_separates_memory_rag_and_project_history_scope() -> None:
    store = EnterpriseMemoryStore()
    memory = PreferenceMemoryStore.in_memory()
    memory.upsert_candidate(
        MemoryCandidate(
            id="memory-source-preference",
            workspace_id="workspace-1",
            project_id="project-1",
            kind="source_preference",
            status="confirmed",
            statement="Prefer official pricing pages before search-only sources.",
            tags=["source", "pricing"],
            match_score=0.91,
        )
    )
    current_evidence = _evidence(
        "evidence-current",
        raw_source_id="source-current",
        title="Cursor pricing",
        quality_label="accepted",
    )
    stale_history = _evidence(
        "evidence-stale-history",
        raw_source_id="source-stale",
        title="Old Cursor pricing",
        quality_label="stale",
    )
    store.upsert_evidence(current_evidence)
    store.upsert_evidence(stale_history)
    version = store.upsert_report_version(
        ReportVersionRecord(
            id="report-v1",
            workspace_id="workspace-1",
            project_id="project-1",
            run_id="run-current",
            version_number=1,
            topic_normalized="cursor-pricing",
            competitor_layer="L1",
            competitor_set_hash="competitor-set",
            report_md="Cursor pricing is current. [source:source-current]",
            evidence_ids=[current_evidence.id],
            quality_metadata={
                "memory_used": {
                    "candidate_ids": ["memory-source-preference"],
                    "prompt_context": [
                        "[memory-source-preference] Prefer official pricing pages."
                    ],
                },
                "rag_gap_fill": {
                    "admitted_evidence_ids": [current_evidence.id],
                    "retrieval_records": [
                        {
                            "evidence_id": current_evidence.id,
                            "chunk_id": "chunk-current",
                            "score": 0.87,
                            "title": current_evidence.title,
                            "source_type": current_evidence.source_type,
                            "dimension": current_evidence.dimension,
                            "snippet": current_evidence.snippet,
                            "retrieval_stage": "hybrid_rerank",
                        },
                        {
                            "evidence_id": stale_history.id,
                            "chunk_id": "chunk-stale",
                            "score": 0.72,
                            "title": stale_history.title,
                            "source_type": stale_history.source_type,
                            "dimension": stale_history.dimension,
                            "snippet": stale_history.snippet,
                            "retrieval_stage": "hybrid_rerank",
                        },
                    ],
                },
            },
        )
    )

    report = build_advisory_context_report(version=version, store=store, memory=memory)
    items = {item.id: item for item in report.items}

    assert report.scope_policy == "report_version_scope_only"
    assert report.memory_candidate_ids == ["memory-source-preference"]
    assert report.report_scope_evidence_ids == [current_evidence.id]
    assert report.project_history_evidence_ids == [stale_history.id]
    assert report.report_scope_item_count == 1
    assert report.advisory_only_item_count >= 2
    assert items["advisory-memory-memory-source-preference"].scope == "advisory_only"
    assert items["advisory-memory-memory-source-preference"].entered_report_scope is False
    assert items["advisory-rag-chunk-current"].scope == "report_scope"
    assert items["advisory-rag-chunk-current"].entered_report_scope is True
    assert items["advisory-rag-chunk-stale"].scope == "advisory_only"
    assert items["advisory-history-evidence-stale-history"].scope == "advisory_only"
    assert version.evidence_ids == [current_evidence.id]


def _evidence(
    evidence_id: str,
    *,
    raw_source_id: str,
    title: str,
    quality_label: str,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-history",
        raw_source_id=raw_source_id,
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title=title,
        url="https://cursor.com/pricing",
        canonical_url="https://cursor.com/pricing",
        snippet=f"{title} evidence snippet.",
        content_hash=f"hash-{evidence_id}",
        reliability_score=0.86,
        freshness_score=0.7,
        quality_label=quality_label,
    )
