from __future__ import annotations

import hashlib
from typing import Any

from packages.enterprise.store import EnterpriseStore, source_registry_from_evidence
from packages.schema.enterprise import (
    EvidenceRecord,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphReadModel,
    SourceRegistryRecord,
)


def build_project_knowledge_graph_read_model(
    *,
    store: EnterpriseStore,
    project_id: str,
) -> KnowledgeGraphReadModel:
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    nodes: dict[str, KnowledgeGraphNode] = {}
    edges: dict[str, KnowledgeGraphEdge] = {}
    evidence = store.list_evidence(project_id=project_id)
    claims = store.list_claims(project_id=project_id)
    reports = store.list_report_versions(project_id=project_id)
    competitors = store.list_competitors(project_id=project_id)
    source_registry = {
        item.id: item for item in store.list_source_registry(workspace_id=project.workspace_id)
    }

    _add_node(
        nodes,
        "project",
        project.id,
        project.name,
        topic=project.topic,
        competitor_layer=project.competitor_layer,
    )
    for competitor in competitors:
        _add_node(
            nodes,
            "competitor",
            competitor.id,
            competitor.name,
            layer=competitor.layer,
            homepage_url=str(competitor.homepage_url) if competitor.homepage_url else "",
        )
        _add_edge(
            edges,
            project.id,
            competitor.id,
            "tracks_competitor",
            metadata={"role": "project_competitor"},
        )

    evidence_by_id = {item.id: item for item in evidence}
    for item in evidence:
        dimension_id = f"dimension:{project_id}:{item.dimension}"
        _add_node(nodes, "dimension", dimension_id, item.dimension)
        _add_edge(edges, project.id, dimension_id, "has_dimension")
        _add_node(
            nodes,
            "evidence",
            item.id,
            item.title,
            dimension=item.dimension,
            source_type=item.source_type,
            reliability_score=item.reliability_score,
            freshness_score=item.freshness_score,
            quality_label=item.quality_label,
            url=str(item.url) if item.url else "",
        )
        _add_edge(edges, dimension_id, item.id, "contains_evidence", evidence_ids=[item.id])
        _add_edge(
            edges,
            item.competitor_id,
            item.id,
            "has_evidence",
            confidence=item.reliability_score,
            evidence_ids=[item.id],
        )
        source = _source_for_evidence(item, source_registry)
        source_registry[source.id] = source
        _add_node(
            nodes,
            "source",
            source.id,
            source.display_name,
            domain=source.domain,
            trust_level=source.trust_level,
            robots_status=source.robots_status,
        )
        _add_edge(
            edges,
            item.id,
            source.id,
            "sourced_from",
            confidence=item.reliability_score,
            evidence_ids=[item.id],
        )

    for claim in claims:
        _add_node(
            nodes,
            "claim",
            claim.id,
            claim.claim_text,
            claim_type=claim.claim_type,
            status=claim.status,
            confidence=claim.confidence,
        )
        _add_edge(
            edges,
            claim.competitor_id,
            claim.id,
            "makes_claim",
            confidence=claim.confidence,
            evidence_ids=claim.evidence_ids,
        )
        for evidence_id in claim.evidence_ids:
            if evidence_id in evidence_by_id:
                _add_edge(
                    edges,
                    claim.id,
                    evidence_id,
                    "supported_by",
                    confidence=claim.confidence,
                    evidence_ids=[evidence_id],
                )

    for report in reports:
        _add_node(
            nodes,
            "report",
            report.id,
            f"Report v{report.version_number}",
            status=report.status,
            run_id=report.run_id,
            version_number=report.version_number,
        )
        _add_edge(edges, project.id, report.id, "has_report_version")
        for claim_id in report.claim_ids:
            if claim_id in nodes:
                _add_edge(edges, report.id, claim_id, "contains_claim")
        for evidence_id in report.evidence_ids:
            if evidence_id in nodes:
                _add_edge(
                    edges,
                    report.id,
                    evidence_id,
                    "cites_evidence",
                    evidence_ids=[evidence_id],
                )

    return KnowledgeGraphReadModel(
        workspace_id=project.workspace_id,
        project_id=project_id,
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=sorted(nodes.values(), key=lambda item: (item.node_type, item.id)),
        edges=sorted(edges.values(), key=lambda item: item.id),
    )


def _source_for_evidence(
    evidence: EvidenceRecord,
    source_registry: dict[str, SourceRegistryRecord],
) -> SourceRegistryRecord:
    derived = source_registry_from_evidence(evidence)
    return source_registry.get(derived.id) or derived


def _add_node(
    nodes: dict[str, KnowledgeGraphNode],
    node_type: str,
    node_id: str,
    label: str,
    **metadata: Any,
) -> None:
    nodes.setdefault(
        node_id,
        KnowledgeGraphNode(
            id=node_id,
            node_type=node_type,  # type: ignore[arg-type]
            label=label,
            metadata={key: value for key, value in metadata.items() if value is not None},
        ),
    )


def _add_edge(
    edges: dict[str, KnowledgeGraphEdge],
    source_id: str,
    target_id: str,
    relation: str,
    *,
    confidence: float = 1.0,
    evidence_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not source_id or not target_id:
        return
    edge_id = _edge_id(source_id, target_id, relation)
    edges.setdefault(
        edge_id,
        KnowledgeGraphEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            confidence=max(0.0, min(1.0, confidence)),
            evidence_ids=evidence_ids or [],
            metadata=metadata or {},
        ),
    )


def _edge_id(source_id: str, target_id: str, relation: str) -> str:
    raw = f"{source_id}|{relation}|{target_id}"
    return f"kg-edge-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"
