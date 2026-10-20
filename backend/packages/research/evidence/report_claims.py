"""Atomic report claims bound to a generation view and complete model review."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from packages.research.evidence.operation_claim_checks import (
    required_operation_checks as required_operation_checks,
    independent_operation_reasons, operation_condition_reasons, operation_review_reasons,
)
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.source_spans import ReportSourceSpanBinding
from packages.research.evidence.snapshot_models import EvidenceArtifactDependency


class ReportConditionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operator: Literal['any_of']
    options: tuple[str, ...] = Field(min_length=2)


class ReportOperationBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation_id: str
    fact_id: str
    source_id: str
    competitor: str
    dimension: str
    operation: str
    object_type: str | None
    object_quote: str | None
    role: str | None
    plan: str | None
    access_scope: str | None
    effect: str
    prerequisites: tuple[dict[str, str], ...]
    condition_evidence: tuple[str, ...]
    operation_quote: str
    condition_groups: tuple[ReportConditionGroup, ...] = ()
    recipient_quote: str | None = None
    excluded_roles: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_legacy_binding(self, handler):
        values = handler(self)
        if not self.condition_groups:
            values.pop('condition_groups', None)
        if self.recipient_quote is None:
            values.pop('recipient_quote', None)
        if not self.excluded_roles:
            values.pop('excluded_roles', None)
        return values


class ReportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    text: str = Field(min_length=1, max_length=600)
    kind: Literal["fact", "inference", "hypothesis"]
    competitor: str
    dimension: str
    fact_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    operation_binding: ReportOperationBinding | None = None
    source_span_bindings: tuple[ReportSourceSpanBinding, ...] = Field(default_factory=tuple, max_length=2)

    @model_serializer(mode="wrap")
    def serialize_legacy_claim(self, handler):
        values = handler(self)
        if self.operation_binding is None:
            values.pop('operation_binding', None)
        if not self.source_span_bindings:
            values.pop('source_span_bindings', None)
        return values

    @field_validator("text")
    @classmethod
    def plain_text(cls, value):
        if any(token in value for token in ("\n", "\r", "[source:", "<", ">", "|", "#")):
            raise ValueError("claim must be plain single-line text without citation or markup injection")
        return value.strip()


class ClaimCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check_id: str
    verdict: Literal['supported', 'unsupported', 'uncertain']
    claim_span: str = Field(max_length=600)


class ClaimReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: str
    verdict: Literal["supported", "unsupported", "uncertain"]
    reason: str = Field(min_length=1, max_length=800)
    checks: tuple[ClaimCheck, ...] = ()

    @model_serializer(mode='wrap')
    def serialize_legacy_review(self, handler):
        values = handler(self)
        if not self.checks:
            values.pop('checks', None)
        return values


class AuditedReportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim: ReportClaim
    status: Literal["supported", "rejected", "unreviewed"]
    review: ClaimReview | None = None
    rule_reasons: tuple[str, ...] = ()


class ReportDimensionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    competitor: str
    dimension: str
    consumption_id: str
    claims: tuple[AuditedReportClaim, ...] = ()
    gaps: tuple[str, ...] = ()
    review_context_bytes: tuple[int, ...] = ()
    answer_coverage: tuple[ReportAnswerCoverage, ...] = ()
    answer_binding_version: Literal[2, 3] | None = None
    claim_review_version: Literal[3] | None = None
    upstream_dependencies: tuple[EvidenceArtifactDependency, ...] | None = None

    @field_validator('answer_binding_version', 'claim_review_version', mode='before')
    @classmethod
    def exact_audit_version(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError('audit version must be an exact integer')
        return value

    @model_serializer(mode='wrap')
    def serialize_legacy_audit(self, handler):
        values = handler(self)
        if not self.answer_coverage:
            values.pop('answer_coverage', None)
        if self.answer_binding_version is None:
            values.pop('answer_binding_version', None)
        if self.claim_review_version is None:
            values.pop('claim_review_version', None)
        if self.upstream_dependencies is None:
            values.pop('upstream_dependencies', None)
        return values


_RECOMMENDATION = re.compile(
    r"适合|更适|最佳|最便宜|预算敏感|开箱即用|见长|推荐|优于|胜出|"
    r"\b(best|better|cheapest|recommended|recommend|ideal|suited|winner)\b", re.I
)
_PROMOTIONAL_PURPOSE = re.compile(
    r"推动团队|赋能.{0,10}团队|支持成长中的团队|支持大型团队|大规模保护数据|"
    r"propel.{0,25}teams?|empower.{0,25}teams?|enable large teams|protect data at scale", re.I
)


def recorded_price_scope_assertion(text):
    """Recorded observations cannot establish an applicable quote or full bill."""
    return bool(re.search(
        r"完整账单|总费用|总成本|实际应付|适用.{0,8}(?:价|报价)|当前.{0,8}(?:价|报价)|"
        r"现价|所有席位|全部席位|全地区|full bill|total cost|applicable (?:price|quote)|"
        r"current (?:applicable )?(?:price|quote)|all (?:seats|regions)", text, re.I
    ))


def _table_row_claim_scoped(text):
    # A passing semantic verdict or an incidental table mention cannot widen a
    # row-only observation to all product comments. Allow explicit table scope.
    universal = re.search(r'(?:所有|全部|任何|一切|每一条)评论|\b(?:all|every|any) comments?\b', text, re.I)
    if universal:
        prefix, suffix = text[:universal.start()], text[universal.end():]
        return bool(re.search(r'表格(?:中|内|里)(?:[，,\s]|的)*$', prefix)
                    or re.match(r'\s+(?:in|on|within)\s+(?:(?:the|a|an)\s+)?tables?\b', suffix, re.I))
    return bool(re.search(r'表格(?:中|内|里|的行)[^。；]{0,30}评论|表格行评论|行评论|'
                          r'\btable(?:[ -]row)? comments?\b|\brow[ -](?:level )?comments?\b|'
                          r'\bcomments? (?:in|on|within) (?:the |a |an )?tables?\b', text, re.I))


def _alternative_condition_promoted(text, groups):
    labels = {re.sub(r'^\s*[-*]\s*', '', option).split(':', 1)[0].strip()
              for group in groups for option in group['options']}
    # Mask labels first: "Only" inside a mode name is not itself an assertion.
    for index, label in enumerate(sorted(labels, key=len, reverse=True)):
        text = re.sub(re.escape(label), f'§mode{index}§', text, flags=re.I)
    has_modes = bool(re.search(r'§mode\d+§', text))
    for part in re.split(r'[。；;.!?]|并且|而且|但是|然而|同时|\b(?:and|but|however)\b', text, flags=re.I):
        modes = set(re.findall(r'§mode\d+§', part))
        # A branch exemption ends at this independent clause. Its condition
        # must name exactly the mode governed by the nearby assertion.
        branch = re.match(r'^\s*(?:(?:当|若|如果)([^，,]{1,120}?)(?:时|则)\s*[,，]?|'
                          r'在([^，,]{1,120}?)下\s*[,，]?|(?:when|if)\s+([^，,]{1,120})\s*[,，])', part, re.I)
        if branch and len(modes) == 1:
            condition = next(value for value in branch.groups() if value is not None)
            if (set(re.findall(r'§mode\d+§', condition)) == modes
                    and re.search(r'选择|设置|设为|模式|\b(?:selected|set|enabled|mode)\b', condition, re.I)):
                # Exempt only the first nearby assertion. A following comma
                # may introduce another global prerequisite or mode denial.
                remainder = re.split(r'[,，]', part[branch.end():], maxsplit=1)
                if len(remainder) == 1:
                    continue
                part = remainder[1]
                modes = set(re.findall(r'§mode\d+§', part))
        mandatory = re.search(r'前提|需要|必须|仅限|只有|仅受邀|\bonly\b|\brequires?\b|\bmust\b', part, re.I)
        denial = re.search(r'不允许|不能|无法|不支持|\bcannot\b|\bcan[’\']t\b|\bnot (?:allowed|available|supported|permitted)\b', part, re.I)
        universal = re.search(r'所有|全部|任何|一律|无论|\b(?:all|every|always|regardless)\b', part, re.I)
        if modes and (mandatory or denial) or has_modes and mandatory and universal:
            return True
    return False


def _claim_operation_effects(text, bound):
    """Read explicit assertions for this action, leaving unknown direction unverified."""
    from packages.research.evidence.operations import OPERATIONS, ROLE_LABELS, _ROLE, _DENIED, operation_matches_text

    # Named access levels and an inviter's prerequisites are not assertions
    # that the claim's subject can perform the bound action.
    text = re.sub(r"[\"'“‘](?:" + ROLE_LABELS + r")[\"'”’]", "§role§", text, flags=re.I)
    text = re.sub(r"((?:拥有|具有|持有|\bwith|\bhas|\bhave)\s+)(?:" + ROLE_LABELS + r")", r"\1§role§", text, flags=re.I)
    parts = re.split(r'[。；;.!?]|\bbut\b|\bhowever\b|但是|但|然而|并且|'
                     r'\band\s+(?=(?:cannot|can|may|must)\b)|[,，]\s*(?=(?:cannot|can|may)\b)', text, flags=re.I)
    effects = set()
    object_pattern = r'\b(pages?|documents?|docs?|boards?|items?|comments?|threads?|workspaces?|content|collections?|rows?|cells?)\b|页面|文档|看板|条目|评论|回复|工作区|内容'
    for part in parts:
        if re.match(r'^\s*(?:前提|条件|requires?\b|provided\b|subject to\b)', part, re.I):
            continue
        if re.match(r'^\s*(?:only if\b|if\b|when\b|只有|仅当|如果|若)', part, re.I):
            condition = re.split(r'[,，]|\bthen\b', part, maxsplit=1, flags=re.I)
            if len(condition) == 2:
                part = condition[1]
        part = re.split(r'前提(?:是|为)|条件(?:是|为)|\b(?:only if|provided that|requires?)\b', part, maxsplit=1, flags=re.I)[0]
        if not operation_matches_text(bound['operation'], part):
            continue
        if (bound['operation'] == 'manage_access'
                and re.search(r'\bmanage\s+(?:access|permissions?|roles?)\b', bound['operation_quote'], re.I)
                and not re.search(r'\bmanage\s+(?:access|permissions?|roles?)\b|管理[^。；，]{0,8}(?:权限|访问)', part, re.I)):
            # Granting edit/view access is not granting the distinct "manage
            # access" capability named by this source-local observation.
            continue
        actors = [m.group().casefold().rstrip('s') for m in _ROLE.finditer(part)
                  if not m.group().casefold().startswith('can ')]
        if (len(set(actors)) > 1 or sum(operation_matches_text(operation, part)
                for operation in OPERATIONS) > 1):
            # A negation belonging to another action/actor must not determine
            # this binding's polarity. Let the existing semantic review decide.
            continue
        if bound.get('role') and actors and bound['role'].casefold().rstrip('s') not in actors:
            continue
        for action in re.finditer(OPERATIONS[bound['operation']][1], part, re.I):
            if bound['operation'] != 'manage_access':
                obj = (re.search(object_pattern, action.group(), re.I) if bound['operation'] in {'create', 'read'} else None)
                after_action = re.split(r'[,，]', part[action.end():], maxsplit=1)[0]
                obj = obj or re.search(object_pattern, after_action, re.I) or re.search(object_pattern, part[:action.start()], re.I)
                if bound.get('object_type') and obj is None:
                    continue
                if obj:
                    value = obj.group().casefold()
                    actual = ('document' if re.fullmatch(r'pages?|documents?|docs?|页面|文档|content|内容', value) else
                              'board' if re.fullmatch(r'boards?|看板', value) else
                              'comment' if re.fullmatch(r'comments?|threads?|评论|回复', value) else
                              'item' if re.fullmatch(r'items?|条目', value) else value.rstrip('s'))
                    expected = bound.get('object_type')
                    expected = 'document' if expected in {'page', 'document', 'content'} else 'comment' if expected in {'comment', 'comment_thread'} else expected
                    if expected and expected != actual:
                        continue
            prefix = re.sub(r'\bnot only\b', '', part[:action.end()], flags=re.I)
            if _DENIED.search(prefix):
                effects.add('denied')
            elif re.search(r'\b(?:can|may|allow(?:s|ed)?|permitted|able to|supports?)\b|可以|允许|能够|有权|支持|'
                           r'可(?=被|对|为|查看|阅读|评论|编辑|创建|分享|管理|修改|授予)', prefix, re.I):
                effects.add('allowed')
    return effects


def claim_rule_reasons(claim, view, boundaries, *, available_facts=None):
    facts = {f.id: f for f in view.facts}
    allowed = {fid for boundary in boundaries for fid in boundary.allowed_fact_ids}
    reasons = []
    # This identifies a collection-status assertion, not product entailment.
    # Product originals cannot certify the server's complete captured/admitted set.
    if re.search(r'(?:所捕获资料|已提供的证据|captured (?:material|evidence|sources)|provided evidence)'
                 r'\s*(?:中)?\s*(?:未包含|没有|未包括|does not (?:include|contain)|did not (?:include|contain))'
                 r'[^。.!?\n]{0,100}(?:定价|计费|价格|pricing|billing|price)', claim.text, re.I):
        reasons.append('collection_status_requires_server_receipt')
    if not claim.fact_ids or not claim.source_ids:
        reasons.append("missing_claim_evidence")
    selected = [facts.get(fid) for fid in claim.fact_ids]
    if any(f is None or f.id not in allowed for f in selected):
        reasons.append("withheld_or_unseen_fact")
    known = [f for f in selected if f is not None]
    if any(f.competitor != claim.competitor or f.dimension != claim.dimension for f in known):
        reasons.append("claim_scope_mismatch")
    if set(claim.source_ids) != {f.source_id for f in known}:
        reasons.append("claim_source_mismatch")
    if claim.dimension == "feature" and not any(f.field == "evidence_terms" for f in known):
        reasons.append("feature_content_fact_required")
    if claim.operation_binding is not None:
        from packages.research.evidence.operations import bound_operation_observation
        bound = bound_operation_observation(claim, facts)
        if bound is None:
            reasons.append('operation_binding_mismatch')
        else:
            effects = _claim_operation_effects(claim.text, bound)
            # Unresolved or mixed-actor polarity still goes through the normal
            # semantic review; a single explicit contrary assertion is blocked.
            if len(effects) == 1 and bound['effect'] not in effects:
                reasons.append('operation_effect_mismatch')
            if bound.get('condition_groups') and _alternative_condition_promoted(claim.text, bound['condition_groups']):
                reasons.append('operation_alternative_condition_promoted')
            reasons.extend(operation_condition_reasons(claim, bound))
    if claim.dimension == 'feature':
        content = [f for f in known if f.field == 'evidence_terms']
        from packages.research.evidence.temporal_conditions import claim_temporal_condition_reasons
        reasons.extend(claim_temporal_condition_reasons(claim, content))
        from packages.research.evidence.source_conditions import claim_source_condition_reasons
        reasons.extend(claim_source_condition_reasons(claim, content))
        from packages.research.evidence.source_exceptions import (
            claim_source_exception_reasons,
            verified_exception_binding,
        )
        from packages.research.evidence.source_spans import projected_source_facts
        projected, span_reasons = projected_source_facts(claim, content)
        reasons.extend(span_reasons)
        # Parent context continues to limit a bound member; it never supports
        # an extra assertion outside that member.
        discovery = view.facts if available_facts is None else available_facts
        reasons.extend(claim_source_exception_reasons(claim, content, available_facts=discovery))
        if not span_reasons and claim.source_span_bindings:
            reasons.extend(claim_temporal_condition_reasons(claim, projected))
            reasons.extend(claim_source_condition_reasons(claim, projected))
            reasons.extend(claim_source_exception_reasons(claim, projected, available_facts=discovery,
                support_quotes=tuple(f.quote for f in projected)))
            from packages.research.evidence.source_exceptions import _ACCESS, _CLARIFY, _asserted, _events
            support = ' '.join(f.quote for f in projected)
            # A source span cannot acquire a new event or access assertion from
            # an unrelated parent value, even if a model returns supported.
            assertion_text = ' '.join(part for part in re.split(r'[.!?。！？;；\n]', claim.text)
                                      if part.strip() and not _CLARIFY.match(part.strip()))
            if (_events(assertion_text) - _events(support)
                    or _asserted(assertion_text, _ACCESS.pattern) and not _ACCESS.search(support)):
                reasons.append('source_span_assertion_outside_support')
        exception_facts = projected if claim.source_span_bindings and not span_reasons else content
        observations = {(f.source_id, f.competitor, f.dimension, f.evidence_item_ids, f.quote) for f in known}
        if ((len({f.id for f in content}) > 1 or len(observations) > 1)
                and not verified_exception_binding(claim, exception_facts)):
            reasons.append('feature_claim_multiple_observations')
        for fact in content:
            from packages.research.evidence.operations import operation_observations
            row_rules = [row for row in operation_observations(fact)
                         if row['object_type'] == 'table_row' and re.search(r'\bonly\b|只能|仅限', row['operation_quote'], re.I)]
            if row_rules and not _table_row_claim_scoped(claim.text):
                reasons.append('operation_object_scope_omitted')
            count = re.search(r'\byou and (?:up to )?(\d+) (?:of your )?teammates\b', fact.quote, re.I)
            if not count:
                continue
            number = int(count[1])
            additive = (re.search(rf'(?:你|本人|自己)\s*(?:和|与|及|加上)\s*(?:最多|至多|不超过)?\s*{number}\s*(?:名|位)?\s*(?:队友|同事|团队成员)', claim.text)
                        or re.search(rf'\byou and (?:up to )?{number} (?:of your )?teammates\b', claim.text, re.I))
            remainder = claim.text[:additive.start()] + claim.text[additive.end():] if additive else claim.text
            totals = re.findall(r'(?:最多|至多|不超过|总共|总计|共计|共有|上限为?|up to|maximum of|a total of)\s*(\d+)\s*(?:人|(?:名|位)(?:用户|编辑者|团队成员|成员)|people\b|editors\b|users\b|participants\b)', remainder, re.I)
            # This quote supplies only one number. After a valid additive
            # phrase, any extra number must be the derived N+1 total.
            extra_numbers = re.findall(r'\d+', remainder)
            if (not additive and str(number + 1) not in totals) or any(int(total) != number + 1 for total in extra_numbers):
                reasons.append('additive_participant_limit_changed_or_omitted')
    if claim.dimension == "feature" and _PROMOTIONAL_PURPOSE.search(claim.text):
        reasons.append("promotional_claim_not_concrete")
    if re.search(r"capability_\d|raw-source-|evidence_terms|capability_keys|billing_interval|billing_cycle", claim.text):
        reasons.append("internal_evidence_metadata_not_product_content")
    if _RECOMMENDATION.search(claim.text):
        # Branch-local observations cannot establish a comparative or buying verdict.
        reasons.append("recommendation_requires_comparable_evidence")
    if claim.kind == "hypothesis":
        reasons.append("hypothesis_not_verified")
    if claim.dimension == "pricing":
        from decimal import Decimal
        from packages.orchestrator.answer_context import _money_pattern, _money_value

        supported_money = {_money_value(f) for f in known if f.id in allowed}
        for match in _money_pattern(facts).finditer(claim.text):
            amount = Decimal((match.group("amount") or match.group("suffix_amount")).replace(",", ""))
            currency = (match.group("prefix") or match.group("suffix")).upper()
            currency = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "CNY", "￥": "CNY", "元": "CNY", "RMB": "CNY"}.get(currency, currency)
            if match.group("prefix_sign") == "-":
                amount = -abs(amount)
            if (amount, currency) not in supported_money:
                reasons.append("amount_not_in_bound_facts")
        if any(b.requirement.intent == "recorded_price" for b in boundaries):
            if recorded_price_scope_assertion(claim.text):
                reasons.append("recorded_price_not_applicable_total")
            missing = {key for b in boundaries for key in b.missing_fields}
            stated_intervals = set()
            if re.search(r"月付|按月付|monthly billing|billed monthly", claim.text, re.I):
                stated_intervals.add("monthly")
            if re.search(r"年付|按年付|annual billing|billed annually", claim.text, re.I):
                stated_intervals.add("annual")
            price_facts = [f for f in known if f.field == "price"]
            if stated_intervals and (not price_facts or any(
                f.qualifiers.get("billing_interval") not in stated_intervals
                for f in price_facts
            ) or len(stated_intervals) != 1):
                reasons.append("unverified_billing_interval")
            if "tax_scope" in missing and re.search(r"含税|免税|税后|tax included|including tax|tax.free", claim.text, re.I):
                reasons.append("unverified_tax_scope")
    return tuple(reasons)


def current_feature_binding_reasons(claim):
    """Replay the current feature transport gate, independent of semantic verdicts."""
    if claim.dimension != 'feature' or claim.operation_binding is not None:
        return ()
    if not claim.source_span_bindings:
        return ('source_span_binding_required',)
    from packages.research.evidence.operations import required_operations
    if required_operations(claim.text):
        return ('operation_binding_required',)
    return ()


def required_claim_checks(claim):
    """Bind whole-assertion judgments to this exact atom and its selected support."""
    support = ([claim.operation_binding.model_dump(mode='json')] if claim.operation_binding else
               [span.model_dump(mode='json') for span in claim.source_span_bindings])
    return [dict(check_id='claim-check-' + hashlib.sha256(json.dumps(
        [claim.id, claim.text, claim.fact_ids, claim.source_ids, support, kind], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24],
        kind=kind, claim_span=claim.text)
        for kind in ('full_assertion_support', 'atomicity')]


def claim_review_reasons(claim, review):
    expected = {row['check_id'] for row in required_claim_checks(claim)}
    checks = [row for row in review.checks if row.check_id in expected]
    reasons = []
    identifiers = [row.check_id for row in checks]
    if set(identifiers) != expected or len(identifiers) != len(expected):
        reasons.append('claim_checks_incomplete')
    if any(row.verdict != 'supported' for row in checks):
        reasons.append('claim_check_not_supported')
    if any(row.claim_span != claim.text for row in checks):
        reasons.append('claim_check_span_invalid')
    operations = {row['check_id'] for row in required_operation_checks(claim.operation_binding)}
    if any(row.check_id not in expected | operations for row in review.checks):
        reasons.append('claim_check_unknown')
    return reasons


def audit_report_claims(claims, reviews, view, boundaries, *, available_facts=None, review_version=None):
    parsed = [ClaimReview.model_validate(r) for r in reviews]
    counts = Counter(r.claim_id for r in parsed)
    claim_counts = Counter(c.id for c in claims)
    by_id = {r.claim_id: r for r in parsed}
    result = []
    for claim in claims:
        rules = list(claim_rule_reasons(claim, view, boundaries, available_facts=available_facts))
        if review_version == 3:
            rules.extend(current_feature_binding_reasons(claim))
            rules.extend(independent_operation_reasons(claim))
        review = by_id.get(claim.id)
        if review is not None:
            operation_review = review
            if review_version == 3:
                rules.extend(claim_review_reasons(claim, review))
                atom_ids = {row['check_id'] for row in required_claim_checks(claim)}
                operation_review = review.model_copy(update={'checks': tuple(
                    row for row in review.checks if row.check_id not in atom_ids)})
            rules.extend(operation_review_reasons(claim, operation_review))
        if claim_counts[claim.id] != 1:
            rules.append("duplicate_claim_id")
        if counts[claim.id] != 1:
            rules.append("missing_or_duplicate_review")
            status = "unreviewed"
        elif rules or review.verdict != "supported":
            status = "rejected"
        else:
            status = "supported"
        result.append(AuditedReportClaim(claim=claim, status=status, review=review, rule_reasons=tuple(rules)))
    return result
