from dataclasses import dataclass

from packages.agents.prompt_contract import EVIDENCE_RULES
from packages.schema.api_dto import RunDetail
from packages.schema.decision_brief import decision_brief_prompt_context


@dataclass(frozen=True)
class ComparatorPrompt:
    system: str
    user: str
    schema_hint: str


def build_comparator_prompt(
    detail: RunDetail, *, analysis_json: str, evidence_json: str
) -> ComparatorPrompt:
    return ComparatorPrompt(
        system=(
            "You are a product-manager competitive intelligence comparator. "
            "Compare products for the user's decision and shared user task. "
            + EVIDENCE_RULES
            + "Analysis JSON may contain evidence_fact_refs with field=value or quote. "
            "Resolve these exact repeated values from the current Evidence View facts only. "
            "Feature capability_keys describe documented presence, not quality or superiority. "
            "Different observation slot/hash values are not different capabilities. "
            "Unknown counterparts and capability_conditions require explicit gaps and winner=null. "
            "A context_budget_exceeded gap means this view omitted collected material, not that no material was collected. "
            + "For each requested dimension return an assessment. Check comparable model, "
            "market/currency, plan/seat, billing interval, tax and time before ranking prices. "
            "Use not_comparable when known conditions differ, insufficient_evidence when "
            "required conditions or source-backed facts are missing. For current price ranking, "
            "missing tax_scope or billing interval for either product always requires "
            "insufficient_evidence and winner=null; a checkout caveat does not make it comparable. "
            "Reserve tie for an "
            "evidence-supported equal outcome. For unresolved assessments set winner to null. "
            "For comparable outcomes identify the scenario, rationale, costs/tradeoffs and "
            "supporting sources for every compared product. More pages or higher source "
            "counts do not prove product superiority. Do not compare annual-equivalent "
            "monthly charges with monthly billing without a supported conversion and scope. "
            "When the product identity is ambiguous request clarification in gaps. "
            "Keep output compact; do not fabricate a complete comparison."
        ),
        user=(
            f"Topic: {detail.topic}\n"
            "Target product: "
            f"{detail.plan.target_product.name if detail.plan.target_product else 'none'}\n"
            f"Competitors: {', '.join(detail.plan.competitors)}\n"
            f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
            f"{decision_brief_prompt_context(detail.plan.decision_brief)}"
            f"Analysis JSON: {analysis_json}\nEvidence View JSON: {evidence_json}"
        ),
        schema_hint=(
            '{"matrix_summary":["short finding"],"assessments":{"dimension":{'
            '"status":"comparable|insufficient_evidence|not_comparable",'
            '"winner":"compared product name, tie, or null",'
            '"rationale":"evidence-supported reason","scenario":"applicable user task",'
            '"tradeoffs":["cost or limitation"],"gaps":["specific missing condition or fact"],'
            '"source_ids":["provided source ID"]}}}'
        ),
    )
