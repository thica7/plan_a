"""Rebuild manual draft claims from the edited body and scoped evidence."""

import re

from packages.business_intel.claim_validator import validate_project_claims
from packages.business_intel.source_reconciliation import evidence_by_source_token, source_tokens
from packages.identity import stable_prefixed_id
from packages.schema.enterprise import (
    ClaimRecord,
    ClaimValidationIssue,
    EvidenceRecord,
    ReportVersionRecord,
)

_CITATION = r"\[\s*(?:source|来源)\s*[:：][^\]]*\]"
_MARKDOWN_LINK = r"\[[^\]]*\]\([^\s)]+\)"
_SUGGESTION = re.compile(
    r"^(?:(?:therefore|thus)[, ]*)?"
    r"(?:we (?:recommend|suggest)|recommend(?:ation)?|suggest|consider|run|conduct|"
    r"compare|test|validate|interview|prioriti[sz]e|evaluate|investigate)\b"
    r"|^(?:因此|所以)?(?:建议|推荐|请|应当)",
    re.IGNORECASE,
)
_REASON = r"(?:\b(?:because|since)\b|因为|由于|因而)\s*"


def _sentence_parts(text: str) -> list[str]:
    """Bind trailing citations to the preceding sentence, never the next one."""
    text = re.sub(r"^\s*\d+[.)]\s+", "", text)
    parts: list[str] = []
    pending = ""
    offset = 0
    for token in re.finditer(
        rf"{_CITATION}|{_MARKDOWN_LINK}|[.!?。！？]", text, re.IGNORECASE,
    ):
        pending += text[offset:token.start()]
        value = token.group()
        offset = token.end()
        if re.fullmatch(_CITATION, value, flags=re.IGNORECASE):
            if pending.strip():
                parts.append(pending.strip() + " " + value)
                pending = ""
            elif parts:
                parts[-1] += " " + value
            else:
                parts.append(value)
            continue
        if value in ".!?。！？" and not pending.strip() and parts and source_tokens(parts[-1]):
            parts[-1] += value
            pending = ""
            continue
        pending += value
        if value.startswith("["):
            continue
        if value == "." and (
            token.start() > 0 and token.end() < len(text)
            and text[token.start() - 1].isdigit() and text[token.end()].isdigit()
        ):
            continue
        if pending.strip():
            parts.append(pending.strip())
            pending = ""
    pending += text[offset:]
    if pending.strip():
        parts.append(pending.strip())
    return parts


def _statement_parts(text: str, product_names: list[str]) -> list[str]:
    subjects = [r"(?:it|they|which|that)\b", "它", "其", "该产品"]
    subjects.extend(rf"{re.escape(name)}(?:\b|(?=[\u4e00-\u9fff]))" for name in product_names)
    continuation = rf"{_REASON}|[,，;；]\s*(?={'|'.join(subjects)})"
    parts = []
    for sentence in _sentence_parts(text):
        link = re.match(r"^\[([^\]]*)\]\([^\s)]+\)(.*)$", sentence.strip(" |-*"))
        if link and _SUGGESTION.match(link[1]):
            sentence = link[1] + link[2]
        if _SUGGESTION.match(sentence.strip(" |-*")):
            clauses = re.split(continuation, sentence, flags=re.IGNORECASE)
        else:
            clauses = [re.sub(rf"^{_REASON}", "", sentence, flags=re.IGNORECASE)]
        parts.extend(clause.strip(" ,，") for clause in clauses if clause.strip(" ,，"))
    return parts


def _is_fact_candidate(text: str, product_names: list[str]) -> bool:
    text = text.strip(" |-*")
    if not text or text.casefold() in {name.casefold() for name in product_names}:
        return False
    link_only = bool(re.fullmatch(rf"(?:{_MARKDOWN_LINK}\s*)+", text))
    if link_only:
        text = " ".join(re.findall(r"\[([^\]]*)\]\(", text))
    if _SUGGESTION.match(text):
        return bool(link_only and re.search(_REASON, text, flags=re.IGNORECASE))
    if not link_only:
        return True
    assertion = re.search(
        r"(?i)\b(?:is|are|was|were|has|have|costs?|lasts?|supports?|offers?|"
        r"includes?|charges?|beats?|outperforms?|exceeds?|guarantees?|always|never|"
        r"forever|best|better|fastest|faster|cheapest|cheaper|highest|lowest|"
        r"most|least|more|less)\b|售价|价格为|支持|具备|拥有|包含|续航为|"
        r"永久|保证|优于|超过|最快|最强|最高|最低|唯一|百分之",
        text,
    )
    quantity = re.search(
        r"[$€£¥￥]\s*\d|\d+(?:\.\d+)?\s*(?:%|％|hours?|days?|users?|buyers?|"
        r"customers?|GB|TB|MHz|GHz|mAh|小时|天|用户|元|万|亿)", text, re.IGNORECASE,
    )
    if assertion or quantity:
        return True
    reference_label = re.compile(
        r"(?i)\b(?:official|website|homepage|pricing|docs?|documentation|specifications?|"
        r"sources?|references?|reviews?|manual|help|overview|release|report)\b|"
        r"官方|官网|文档|来源|参考|手册|评测|综述|规格|报告",
    )
    for name in product_names:
        subject = re.match(rf"^{re.escape(name)}(?:\b|(?=[：:—\s]))", text, re.IGNORECASE)
        if subject:
            predicate = text[subject.end():].strip(" :：—-")
            if reference_label.match(re.sub(r"^\d+\s*", "", predicate)):
                return False
            if predicate and not re.fullmatch(r"\d+|[A-Z][\w-]*", predicate):
                return True
    return False


def _line_parts(text: str, product_names: list[str]) -> list[str]:
    if not text.startswith("|"):
        return _statement_parts(text, product_names)
    cells = [cell.strip() for cell in text.strip("|").split("|")]
    parts = [part for cell in cells for part in _statement_parts(cell, product_names)]
    citation_cells = [part for part in parts if not re.sub(
        _CITATION, "", part, flags=re.IGNORECASE,
    ).strip()]
    facts = [part for part in parts if _is_fact_candidate(re.sub(
        _CITATION, "", part, flags=re.IGNORECASE,
    ), product_names)]
    # An evidence column can support a single fact; multi-fact rows bind citations inline.
    if len(facts) == 1 and citation_cells:
        return [facts[0] + " " + " ".join(citation_cells)]
    return parts


_NEUTRAL_LABELS = {
    "executive summary", "summary", "overview", "product comparison", "comparison",
    "competitive findings", "evidence", "sources", "references", "pricing", "price",
    "features", "feature", "personas", "persona", "limitations", "confidence",
    "evidence & limitations", "evidence and limitations", "recommendations", "next steps",
    "claim", "claims", "revised", "修订", "排版",
    "product", "products", "operation", "operations", "dimension", "dimensions", "plan",
    "role", "access", "object", "currency", "seat", "monthly", "annual", "swot",
    "摘要", "概览", "一句话结论", "核心结论", "结论", "产品分析", "产品对比", "竞品分析",
    "竞品对比", "对比矩阵", "产品", "操作", "维度", "证据", "来源", "引用", "参考资料",
    "价格", "定价", "功能", "用户画像", "局限", "限制", "证据与限制", "建议", "下一步",
    "套餐", "角色", "访问前提", "对象", "货币", "席位", "月付", "年付",
}


def _neutral_label(text: str, product_names: list[str]) -> bool:
    """Only explicit section/column labels may bypass assertion review."""
    text = re.sub(r"\[([^\]]*)\]\([^\s)]+\)", r"\1", text)
    text = _format_equivalent(re.sub(r"^\d+[.)、]\s*", "", text)).casefold()
    if not text or text in _NEUTRAL_LABELS:
        return True
    for product in product_names:
        product = _format_equivalent(product).casefold()
        if text == product:
            return True
        if product and text.startswith(product):
            remainder = text[len(product):].strip(" :：—-")
            if remainder in _NEUTRAL_LABELS:
                return True
    return False


def validate_manual_revision(
    version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
    *,
    verified_claims: dict[str, set[str]] | None = None,
) -> tuple[list[ClaimRecord], dict[str, object]]:
    by_token = evidence_by_source_token(evidence)
    claims: list[ClaimRecord] = []
    unbound: list[dict[str, object]] = []
    stored_plan = version.quality_metadata.get("analysis_plan") or {}
    product_names = [item.competitor_id for item in evidence]
    if isinstance(stored_plan, dict):
        product_names.extend(stored_plan.get("competitors") or [])
        target = stored_plan.get("target_product")
        if isinstance(target, dict) and target.get("name"):
            product_names.append(target["name"])
    product_names = [name for name in product_names if isinstance(name, str) and name]
    lines = version.report_md.splitlines()
    body_parts = []
    for line_number, line in enumerate(lines, start=1):
        text = re.sub(r"^[-*+]\s+", "", line.strip())
        if not text or text.startswith("<!--") or re.fullmatch(r"[|:\s-]+", text):
            continue
        force_review = False
        heading = re.match(r"^#{1,6}(?:\s+|$)", text)
        if heading:
            text = re.sub(r"\s+#+\s*$", "", text[heading.end():]).strip()
            heading_text = re.sub(_CITATION, "", text, flags=re.IGNORECASE)
            if _neutral_label(heading_text, product_names) and not source_tokens(text):
                continue
            force_review = True
        if (
            text.startswith("|")
            and line_number < len(lines)
            and re.fullmatch(r"[|:\s-]+", lines[line_number])
        ):
            # Table headers can contain assertions too. Keep unknown cells and
            # citations, removing only known structural labels before binding.
            columns = []
            for cell in text.strip("|").split("|"):
                label = re.sub(_CITATION, "", cell, flags=re.IGNORECASE).strip()
                if _neutral_label(label, product_names):
                    columns.extend(re.findall(_CITATION, cell, flags=re.IGNORECASE))
                else:
                    columns.append(cell)
            if not columns:
                continue
            text = "|" + "|".join(columns) + "|"
            force_review = True
        parts = _line_parts(text, product_names)
        body_parts.extend((line_number, index, part, force_review)
                          for index, part in enumerate(parts))
    for line_number, part_index, text, force_review in body_parts:
        cited = {
            item.id: item
            for token in source_tokens(text)
            if (item := by_token.get(token)) is not None
        }
        claim_text = re.sub(
            _CITATION,
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" |-")
        if not claim_text or (
            not force_review and not _is_fact_candidate(claim_text, product_names)
        ):
            continue
        if not cited:
            unbound.append({"line_number": line_number, "claim_text": claim_text})
            continue
        first = next(iter(cited.values()))
        claims.append(
            ClaimRecord(
                id=stable_prefixed_id(
                    "claim-manual",
                    version.id,
                    line_number,
                    part_index,
                    claim_text,
                    length=16,
                ),
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                run_id=version.run_id,
                competitor_id=first.competitor_id,
                claim_type=first.dimension,
                claim_text=claim_text,
                evidence_ids=list(cited),
                confidence=min(item.reliability_score for item in cited.values()),
                created_by_agent="manual_revision",
            )
        )
    validation = validate_project_claims(
        project_id=version.project_id,
        claims=claims,
        evidence=evidence,
    )
    # Lexical overlap is not entailment. Only complete source statements or
    # unchanged claims from a current, independently audited producer can pass
    # this manual-edit shortcut. New wording needs semantic/human review.
    pending = []
    by_id = {item.id: item for item in evidence}
    for result, claim in zip(validation.results, claims, strict=True):
        usable = [by_id[eid] for eid in result.usable_evidence_ids]
        text = _format_equivalent(claim.claim_text)
        source_match = any(text == _format_equivalent(item.snippet) for item in usable)
        audited_match = set(claim.evidence_ids) == (verified_claims or {}).get(text)
        if audited_match and len(usable) == len(claim.evidence_ids):
            result.status = "supported"
            result.validation_status = "supported"
            result.recommended_action = "none"
            result.rationale = "Unchanged claim replays the current source-bound semantic audit."
        elif not source_match:
            result.status = "blocked"
            result.validation_status = "unsupported"
            result.recommended_action = "human_review"
            result.rationale = (
                "Changed manual assertion requires semantic or human review; "
                "lexical overlap is insufficient."
            )
            pending.append(claim.id)
            issue = ClaimValidationIssue(
                id=stable_prefixed_id("manual-semantic-review", version.id, claim.id, length=16),
                claim_id=claim.id,
                severity="blocker",
                issue_type="weak_text_support",
                message="人工修订新增或改写了事实，需补证或语义/人工复核；词语重合不能证明条件成立。",
                evidence_ids=claim.evidence_ids,
            )
            validation.issues.append(issue)
            result.issue_ids.append(issue.id)
    validation.issue_count = len(validation.issues)
    validation.blocker_count = sum(item.severity == "blocker" for item in validation.issues)
    validation.warn_count = sum(item.severity == "warn" for item in validation.issues)
    validation.weak_count = sum(item.status == "weak" for item in validation.results)
    validation.unsupported_count = sum(item.status == "unsupported" for item in validation.results)
    validation.supported_count = sum(item.status == "supported" for item in validation.results)
    validation.blocked_count = sum(item.status == "blocked" for item in validation.results)
    validation.validation_status_counts = {
        key: sum(item.validation_status == key for item in validation.results)
        for key in validation.validation_status_counts
    }
    findings = [
        {
            "id": stable_prefixed_id("qa-manual", version.id, result.claim_id, length=16),
            "severity": "blocker"
            if (
                result.status in {"blocked", "unsupported"}
                or result.text_support_score < 40
                or result.high_risk
            )
            else "warn",
            "detected_by": "claim_validator",
            "target_agent": "writer",
            "field_path": "manual_revision.current_body",
            "problem": f"Current manual claim is {result.status}: {result.claim_id}",
            "metadata": {
                "claim_ids": [result.claim_id],
                "evidence_ids": result.usable_evidence_ids,
            },
        }
        for result in validation.results
        if result.status != "supported"
    ]
    findings.extend(
        {
            "id": stable_prefixed_id(
                "qa-manual-unbound",
                version.id,
                item["line_number"],
                item["claim_text"],
                length=16,
            ),
            "severity": "blocker",
            "detected_by": "citation",
            "target_agent": "writer",
            "field_path": f"report_md.line[{item['line_number']}]",
            "problem": "Current manual claim has no scoped source citation.",
            "metadata": item,
        }
        for item in unbound
    )
    return claims, {
        "run_qa_findings": findings,
        "run_qa_blocker_count": sum(item["severity"] == "blocker" for item in findings),
        "run_qa_warning_count": sum(item["severity"] == "warn" for item in findings),
        "manual_claim_validation": validation.model_dump(mode="json"),
        "manual_semantic_review": {
            "status": "pending_review"
            if (
                pending or unbound or any(item.status != "supported" for item in validation.results)
            )
            else "checked",
            "pending_claim_ids": pending,
            "policy": "complete_source_or_current_audited_claim.v1",
        },
        "unresolved_manual_claims": unbound,
    }


def _format_equivalent(text: str) -> str:
    text = re.sub(r"(\*\*|__|`)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)([*_])([^*_]+)\1(?!\w)", r"\2", text)
    return re.sub(r"\s+", " ", text).strip(" .!?。！？")
