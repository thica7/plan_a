"""Answer explicit quote requests with a reproducible admitted-evidence gap."""

from __future__ import annotations

import re
from datetime import date

from packages.research.evidence.answer_guard import (
    _day,
    _is_money,
    _money_fields,
    evaluate_answer_boundary,
)
from packages.research.evidence.answer_models import AnswerRequirement
from packages.research.evidence.snapshot import _verify, current_snapshot
from packages.research.evidence.snapshot_models import (
    FACT_MARKET_POLICY_VERSION,
    StageEvidenceView,
    canonical_json,
)

_MARKETS = {
    "CN": r"中国|中国大陆|\bChina\b|\bCN\b",
    "US": r"美国|\bUnited States\b|\bUSA?\b",
    "GB": r"英国|\bUnited Kingdom\b|\bUK\b|\bGB\b",
    "EU": r"欧盟|\bEuropean Union\b|\bEU\b",
    "JP": r"日本|\bJapan\b|\bJP\b",
}
_CURRENCIES = {
    "CNY": r"人民币|(?<![A-Za-z])(?:CNY|RMB)(?![A-Za-z])",
    "USD": r"美元|(?<![A-Za-z])USD(?![A-Za-z])|US\$",
    "EUR": r"欧元|(?<![A-Za-z])EUR(?![A-Za-z])|€",
    "GBP": r"英镑|(?<![A-Za-z])GBP(?![A-Za-z])|£",
    "JPY": r"日元|(?<![A-Za-z])JPY(?![A-Za-z])",
}
_MONTHLY = r"月费|月付|按月|每月|月度|\bmonthly\b|\bper month\b|\ba month\b"
_ANNUAL = r"年费|年付|按年|每年|年度|\bannual(?:ly)?\b|\byearly\b|\bper year\b"
_TAX_INCLUDED = r"含税|税后|tax[- ]inclusive|tax included|including tax|with tax|gross price"
_TAX_EXCLUDED = r"不含税|未含税|未税|税前|tax[- ]exclusive|tax excluded|excluding tax|before tax"


def _one_match(text, patterns):
    matches = [key for key, pattern in patterns.items() if re.search(pattern, text, re.I)]
    return matches[0] if len(matches) == 1 else None


def _plan(text, product):
    text = re.sub(re.escape(product), " ", text, flags=re.I)
    names = []
    for pattern in (
        r'["“]([^"”]+)["”]\s*(?:套餐|方案|plan|tier)',
        r'\b(?:plan|tier)\s+["“]([^"”]+)["”]',
        r"([A-Za-z][A-Za-z0-9_+-]*)\s*(?:套餐|方案|计划|版)",
        r"\b([A-Za-z][A-Za-z0-9_+-]*)\s+(?:plan|tier)\b",
    ):
        names.extend(match.group(1).strip() for match in re.finditer(pattern, text, re.I))
    for label, name in (("企业版", "Enterprise"), ("专业版", "Pro"), ("免费版", "Free")):
        if label in text:
            names.append(name)
    unique = {name.casefold(): name for name in names}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _request(detail, question, product):
    text = question["question"]
    if not re.search(r"价格|报价|月费|年费|金额|多少钱|\b(?:price|cost|fee|quote)\b", text, re.I):
        return None
    if not re.search(r"多少|准确|具体金额|\bhow much\b|\bexact\b|\bwhat\b", text, re.I):
        return None
    dates = set(re.findall(
        r"(?:截至|截止|报价日期|价格日期|\bas of\b|\bprice (?:on|at)\b)\s*[:：]?\s*"
        r"(\d{4}-\d{2}-\d{2})(?!\d)", text, re.I))
    for year, month, day in re.findall(
        r'(?:截至|截止|报价日期|价格日期)\s*[:：]?\s*'
        r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text):
        try:
            dates.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            return None
    if dates:
        if len(dates) != 1:
            return None
        try:
            as_of = date.fromisoformat(next(iter(dates)))
        except ValueError:
            return None
    else:
        as_of = _day(detail.created_at)
    if as_of is None:
        return None
    market = _one_match(text, _MARKETS)
    currency = _one_match(text, _CURRENCIES)
    plan = _plan(text, product)
    monthly, annual = bool(re.search(_MONTHLY, text, re.I)), bool(re.search(_ANNUAL, text, re.I))
    # An unspecified or ambiguous quote scope needs clarification rather than
    # an automatic "answered" record. Request text never supplies evidence.
    if not market or not currency or not plan or monthly == annual:
        return None
    tax = None
    if re.search(_TAX_EXCLUDED, text, re.I):
        tax = "tax_excluded"
    elif re.search(_TAX_INCLUDED, text, re.I):
        tax = "tax_included"
    context = {
        "currency": currency,
        "plan": plan,
        "billing_interval": "monthly" if monthly else "annual",
    }
    if tax:
        context["tax_scope"] = tax
    return market, as_of, context


def _validate_snapshot(detail, snapshot, product):
    _verify(snapshot)
    current = current_snapshot(detail)
    if (
        current is None
        or current.id != snapshot.id
        or current.content_hash != snapshot.content_hash
    ):
        raise ValueError("missing-price answers require the current evidence snapshot")
    if (
        snapshot.run_id != detail.id
        or snapshot.workspace_id != detail.workspace_id
        or snapshot.project_id != detail.project_id
    ):
        raise ValueError("missing-price evidence scope mismatch")
    if (
        detail.evidence_inputs_dirty
        or snapshot.phase != "analysis"
        or snapshot.fact_market_policy_version != FACT_MARKET_POLICY_VERSION
    ):
        raise ValueError("missing-price answers require accepted evidence")
    if product not in detail.plan.competitors:
        raise ValueError("missing-price product scope mismatch")


def _complete_views(snapshot, product):
    """Local audit objects: no prompt serialization, selection limit or wall clock.

    Keep immutable source status/role/dates so answer_guard can evaluate all
    originals against the fixed question as_of, including during later replay.
    """
    dimensions = sorted({fact.dimension for fact in snapshot.facts if fact.competitor == product})
    if not dimensions:
        dimensions = ["pricing"]
    views = []
    for dimension in dimensions:
        sources = tuple(
            source
            for source in snapshot.sources
            if source.dimension == dimension
            and product in (source.competitor, *source.covered_competitors)
            and source.document_workspace_id in (None, snapshot.workspace_id)
            and source.document_project_id in (None, snapshot.project_id)
        )
        facts = tuple(
            fact
            for fact in snapshot.facts
            if fact.competitor == product and fact.dimension == dimension
        )
        views.append(
            StageEvidenceView(
                agent="writer",
                run_id=snapshot.run_id,
                workspace_id=snapshot.workspace_id,
                project_id=snapshot.project_id,
                snapshot_id=snapshot.id,
                snapshot_version=snapshot.version,
                content_hash=snapshot.content_hash,
                competitor=product,
                dimension=dimension,
                sources=sources,
                facts=facts,
                source_ids=tuple(source.id for source in sources),
                fact_ids=tuple(fact.id for fact in facts),
                conflicts=tuple(
                    conflict
                    for conflict in snapshot.conflicts
                    if conflict.competitor == product and conflict.dimension == dimension
                ),
                dependency_hash=snapshot.content_hash,
            )
        )
    return views


def _scope_gaps(fields, context):
    aliases = {
        "monthly": "monthly",
        "month": "monthly",
        "per_month": "monthly",
        "annual": "annual",
        "annually": "annual",
        "yearly": "annual",
        "year": "annual",
        "tax_included": "tax_included",
        "included": "tax_included",
        "tax_inclusive": "tax_included",
        "vat_included": "tax_included",
        "tax_excluded": "tax_excluded",
        "excluded": "tax_excluded",
        "tax_exclusive": "tax_excluded",
    }
    return {
        key
        for key in ("billing_interval", "tax_scope")
        if key in context and aliases.get(str(fields.get(key)).casefold()) != context[key]
    }


def server_missing_price_answers(detail, snapshot, questions, product) -> dict[str, dict]:
    """Resolve admitted-snapshot quote gaps, without asserting market-wide absence."""
    _validate_snapshot(detail, snapshot, product)
    if any(
        gap.reason == "context_budget_exceeded" and gap.competitor in (None, product)
        for gap in snapshot.gaps
    ):
        return {}
    views = _complete_views(snapshot, product)
    result = {}
    for question in questions:
        parsed = _request(detail, question, product)
        if parsed is None:
            continue
        market, as_of, context = parsed
        missing = {"current_price"}
        found = False
        for view in views:
            requirement = AnswerRequirement(
                competitor=product,
                dimension=view.dimension,
                intent="current_price",
                market=market,
                as_of=as_of,
                context_json=canonical_json(context),
            )
            boundary = evaluate_answer_boundary(view, requirement)
            missing.update(boundary.missing_fields)
            money = {fact.id: fact for fact in view.facts if _is_money(fact)}
            for fact_id in boundary.allowed_fact_ids:
                if fact_id not in money:
                    continue
                extra = _scope_gaps(_money_fields(money[fact_id]), context)
                missing.update(extra)
                if not extra:
                    found = True
        if found:
            continue
        scope = (
            f"{market}、{context['plan']} 套餐、{context['currency']}、"
            f"{context['billing_interval']}"
        )
        if "tax_scope" in context:
            scope += "、" + ("含税" if context["tax_scope"] == "tax_included" else "不含税")
        result[question["question_id"]] = {
            "question_id": question["question_id"],
            "question": question["question"],
            "status": "answered",
            "resolution": "insufficient",
            "conclusion": "unknown",
            "answer": f"本次已准入资料不足以核实截至 {as_of.isoformat()}、{scope}的当前报价，"
            "因此无法给出该口径的准确金额。",
            "claim_ids": (),
            "evidence_spans": (),
            "missing_fields": tuple(sorted(missing)),
            "reason": f"server_missing_current_price;as_of={as_of.isoformat()};scope={scope}",
            "basis_snapshot_id": snapshot.id,
        }
    return result
