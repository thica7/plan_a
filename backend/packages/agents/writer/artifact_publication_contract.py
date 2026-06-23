from __future__ import annotations

from packages.agents.writer.publication_contract import (
    PublicationContractIssue,
    PublicationContractResult,
    validate_publication_contract,
)
from packages.agents.writer.structured_hygiene import SOURCE_TOKEN_RE
from packages.schema.report_artifact import ReportArtifactV2


def validate_report_artifact_publication(
    artifact: ReportArtifactV2,
    *,
    allowed_source_ids: set[str] | None = None,
) -> PublicationContractResult:
    issues: list[PublicationContractIssue] = []
    full_markdown = artifact.render_cache.full_markdown
    if full_markdown and not artifact.render_cache.core_markdown:
        issues.append(
            PublicationContractIssue(
                code="full_markdown_without_core_markdown",
                line_number=1,
                message="Report artifact full markdown is populated without core markdown.",
                repair_target="artifact_assembler",
            )
        )
    expected_full_markdown = "\n\n".join(
        markdown
        for markdown in (
            artifact.render_cache.core_markdown,
            artifact.render_cache.support_markdown,
            artifact.render_cache.audit_markdown,
        )
        if markdown
    )
    if artifact.render_cache.full_markdown != expected_full_markdown:
        issues.append(
            PublicationContractIssue(
                code="full_markdown_cache_mismatch",
                line_number=1,
                message="Report artifact full markdown does not match layer markdowns.",
                repair_target="artifact_assembler",
            )
        )

    citation_allowed_source_ids = _citation_allowed_source_ids(
        artifact,
        full_markdown=full_markdown,
        allowed_source_ids=allowed_source_ids,
    )
    if allowed_source_ids is not None:
        issues.extend(
            _artifact_source_registry_issues(
                artifact,
                allowed_source_ids=allowed_source_ids,
            )
        )
    output_language = artifact.metadata.get("output_language")
    markdown_result = validate_publication_contract(
        full_markdown,
        structured_report=None,
        allowed_source_ids=citation_allowed_source_ids,
        output_language=output_language if isinstance(output_language, str) else None,
    )
    return PublicationContractResult(
        passed=not issues and markdown_result.passed,
        issues=[*issues, *markdown_result.issues],
    )


def _citation_allowed_source_ids(
    artifact: ReportArtifactV2,
    *,
    full_markdown: str,
    allowed_source_ids: set[str] | None,
) -> set[str]:
    if allowed_source_ids is not None:
        return set(allowed_source_ids)
    if artifact.legacy.source == "report_md":
        return _well_formed_cited_source_ids(full_markdown)
    return set()


def _well_formed_cited_source_ids(markdown: str) -> set[str]:
    source_ids: set[str] = set()
    for match in SOURCE_TOKEN_RE.finditer(markdown):
        token = match.group(0)
        source_ids.add(token[token.find(":") + 1 : -1])
    return source_ids


def _artifact_source_registry_issues(
    artifact: ReportArtifactV2,
    *,
    allowed_source_ids: set[str],
) -> list[PublicationContractIssue]:
    issues: list[PublicationContractIssue] = []
    for source_id in sorted(_artifact_source_ids(artifact) - allowed_source_ids):
        issues.append(
            PublicationContractIssue(
                code="artifact_source_outside_registry",
                line_number=1,
                message=(
                    "Report artifact source metadata references an ID outside the "
                    "authoritative source registry."
                ),
                repair_target="artifact_assembler",
                excerpt=source_id,
            )
        )
    return issues


def _artifact_source_ids(artifact: ReportArtifactV2) -> set[str]:
    source_ids: set[str] = set()
    for layer in (
        artifact.core_report,
        artifact.support_appendix,
        artifact.audit_log,
    ):
        for section in layer.sections:
            source_ids.update(section.source_ids)
    for brief in artifact.section_briefs:
        source_ids.update(brief.allowed_source_ids)
    for bundle in artifact.claim_card_bundles:
        source_ids.update(bundle.source_ids)
        for card in bundle.cards:
            source_ids.update(card.source_ids)
    if artifact.decision_card_bundle is not None:
        for card in artifact.decision_card_bundle.cards:
            source_ids.update(card.source_ids)
    return source_ids


__all__ = ["validate_report_artifact_publication"]
