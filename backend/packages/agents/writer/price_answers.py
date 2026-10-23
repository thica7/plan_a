"""Answer explicit quote requests with a reproducible admitted-evidence gap."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from types import SimpleNamespace

from packages.research.evidence.answer_guard import (
    _day,
    _is_money,
    _money_fields,
    evaluate_answer_boundary,
)
from packages.research.evidence.answer_models import AnswerRequirement
from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
from packages.research.evidence.snapshot import _verify, current_snapshot
from packages.research.evidence.snapshot_models import (
    FACT_MARKET_POLICY_VERSION,
    StageEvidenceView,
    canonical_json,
)
from packages.research.evidence.source_spans import projected_source_facts
from packages.research.evidence.temporal_conditions import _source_strings
from packages.research.evidence.views import _qualification
from packages.research.extraction.billing_rules import billing_rule_text_signal

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
_MONTHLY = r"月费|月付|按月|每月|月度|本月|这个月|\bmonthly\b|\bper month\b|\ba month\b"
_ANNUAL = r"年费|年付|按年|每年|年度|\bannual(?:ly)?\b|\byearly\b|\bper year\b"
_PURCHASE = r'购买|采购|订购|买|\b(?:buy|purchase)\b'
_TAX_INCLUDED = r"含税|税后|tax[- ]inclusive|tax included|including tax|with tax|gross price"
_TAX_EXCLUDED = r"不含税|未含税|未税|税前|tax[- ]exclusive|tax excluded|excluding tax|before tax"
_EN_AMOUNT_OBJECT = r'(?:price|costs?|fees?|quote|bill|invoice|amount|total)'
_EN_AMOUNT_MODIFIERS = (
    r'(?:(?:the|our|your|current|total|monthly|annual|exact|accurate|'
    r'tax[- ]inclusive|tax[- ]exclusive|CNY|USD|EUR|GBP|JPY)\s+)*'
)
_EN_AMOUNT_END = r'(?=\s*(?:[?？.,;:]|$|\b(?:for|of|in|on|per|as of)\b))'
_EN_AMOUNT_REQUEST = re.compile(
    r'\b(?:what\s+(?:is|are|would be|will be)|how much\s+(?:is|are|would be|will be))\s+'
    + _EN_AMOUNT_MODIFIERS + _EN_AMOUNT_OBJECT + _EN_AMOUNT_END
    + r'|\bexact\s+' + _EN_AMOUNT_MODIFIERS + _EN_AMOUNT_OBJECT + _EN_AMOUNT_END
    + r'|\bhow much\s+(?:does|do|would|will|should|we|I|to)\b'
    r'[^.!?\n]{0,100}\b(?:cost|pay|owe|charge)\b' + _EN_AMOUNT_END,
    re.I,
)


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
    if not unique:
        products = _purchase_products(text)
        if products:
            return " + ".join(products)
    return next(iter(unique.values())) if len(unique) == 1 else None


_BILLING_SCOPE_LABELS = {
    'plan': r'\b(?:plans?|tiers?)\b|套餐|方案|免费版|企业版',
    'usage_model': r'\busage models?\b|用量模式',
}
_BILLING_NAME = r'[A-Z][A-Za-z0-9_+-]*(?:\s+[A-Z][A-Za-z0-9_+-]*){0,4}'


def _purchase_products(text):
    """Preserve explicitly requested names without asserting a marketed SKU."""
    purchase = re.search(_PURCHASE, text, re.I)
    if not purchase:
        return []
    match = re.match(
        r'\s*[“"]?(' + _BILLING_NAME + r'(?:\s*(?:和|及|与|、|\+|(?i:and))\s*'
        + _BILLING_NAME + r')*)[”"]?', text[purchase.end():],
    )
    return re.split(r'\s*(?:和|及|与|、|\+|\band\b)\s*', match[1], flags=re.I) if match else []


def _billing_name_matches(text):
    """One grammar supplies both exact names and their complete source spans."""
    name = '(' + _BILLING_NAME + ')'
    return {
        axis: tuple(re.finditer(r'(?<![A-Za-z0-9_+-])' + name + suffix, text))
        for axis, suffix in (('plan', r'\s+(?i:plans?|tiers?)\b'),
                             ('usage_model', r'\s+(?i:usage models?)\b'))
    }


def _billing_names(text):
    return {
        axis: {re.sub(r'^The\s+', '', match[1]).strip() for match in matches}
        for axis, matches in _billing_name_matches(text).items()
    }


def _source_billing_names(fact):
    """Names from the same admitted original, never a vendor/SKU dictionary."""
    return _billing_names('\n'.join(dict.fromkeys(value for _, value in _source_strings(fact))))


def _source_matched_request_scope(text, facts):
    matched = {'plan': set(), 'usage_model': set()}
    for fact in facts:
        names = _source_billing_names(fact)
        current = {axis: {name for name in candidates
                         if re.search(r'(?<![A-Za-z0-9_+-])' + re.escape(name)
                                      + r'(?![A-Za-z0-9_+-])', text, re.I)}
                   for axis, candidates in names.items()}
        # The mode and named plan must be matched within this same original.
        if all(not names[axis] or current[axis] for axis in names):
            for axis in matched:
                matched[axis].update(current[axis])
    return {axis: next(iter(names)) for axis, names in matched.items() if len(names) == 1}


def _request(detail, question, product, *, source_facts=()):
    text = question["question"]
    if not re.search(r"价格|定价|报价|月费|年费|金额|多少钱|总价|账单|"
                     r"\b(?:pric(?:e|ing)|costs?|fees?|quotes?|bill|invoice)\b", text, re.I):
        return None
    if not re.search(r"多少钱|多少(?:美元|人民币|欧元|金额)|具体金额|"
                     r"(?:价格|报价|月费|年费|金额|总价|费用|成本|账单)"
                     r"(?:\s|当前|目前|准确|精确|含税|不含税|总计|合计|共计|实际|应付|预计|大约|到底|为|是|需|要|的|[:：]){0,8}"
                     r"多少(?!种|个|角色|天|年|月|条)|"
                     r"(?:精确|准确)[^。？！?\n]{0,50}(?:金额|总价|报价)|"
                     r"\bhow much(?:\s+money)?\s*[?？]?$", text, re.I) and not _EN_AMOUNT_REQUEST.search(text):
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
    tax = None
    if re.search(_TAX_EXCLUDED, text, re.I):
        tax = "tax_excluded"
    elif re.search(_TAX_INCLUDED, text, re.I):
        tax = "tax_included"
    context = {key: value for key, value in {
        "currency": currency, "plan": plan,
        "billing_interval": ("monthly" if monthly else "annual") if monthly != annual else None,
    }.items() if value is not None}
    context.update(_source_matched_request_scope(text, source_facts))
    if tax:
        context["tax_scope"] = tax
    products = _purchase_products(re.sub(re.escape(product), ' ', text, flags=re.I))
    if products:
        context['requested_products'] = products
    if re.search(_PURCHASE, text, re.I):
        duration = re.search(r'(?<![\d-])(一|两|[1-9]\d{0,2})\s*(年|个月|years?|months?)'
                             r'(?!\s*\d+\s*月)', text, re.I)
        if duration:
            count = {'一': 1, '两': 2}.get(duration[1])
            if count is None:
                count = int(duration[1])
            context['duration_months'] = count * (12 if duration[2].casefold() in {'年', 'year', 'years'} else 1)
    employees = re.search(r'(\d+)\s*(?:名|位|个)?\s*(?:员工|employees?)', text, re.I)
    if employees:
        context['employee_count'] = int(employees[1])
    billable_seats = re.search(r'(?:实际)?付费席位\s*(?:为|是|[:：])?\s*(\d+)', text)
    if billable_seats:
        context['billable_seats'] = int(billable_seats[1])
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


def _positive_cpu_time_rate(value, header=''):
    """One monetary rate with a time denominator, shared by prose and its table cell."""
    from decimal import Decimal
    rates = re.finditer(
        r'(?<![-\w])(?:[$€¥]|\b(?:USD|EUR|CNY)\s*)\s*(\d+(?:\.\d+)?)\s*'
        r'(?:per|/)\s*(?:additional\s+)?'
        r'(?:(?:million|billion|\d[\d,]*)(?:\s+(?:million|billion))?\s*)?'
        r'(?:(?:CPU\s+)?(?P<unit>milliseconds?|ms|seconds?)\b)?'
        r'(?=$|\s*(?:[;,.()]|Max\b))', value, re.I)
    return any(Decimal(rate[1]) > 0 and not re.search(r'-\s*$', value[:rate.start()])
               and (rate['unit'] or re.search(r'\b(?:milliseconds?|ms|seconds?)\b', header, re.I))
               for rate in rates)


def _unknown_billing_scope(text):
    matches = _billing_name_matches(text)
    return any(not any(named.start() <= scope.start() and scope.end() <= named.end()
                       for named in matches[axis])
               for axis, label in _BILLING_SCOPE_LABELS.items()
               for scope in re.finditer(label, text, re.I))


def _matching_billing_applicability(source_text, requested):
    """Finite affirmative access grammar, not general pricing entailment.

    A complete relevant plan+mode sentence must match every word. A denial,
    quotation, conditional or unknown remainder cannot borrow a positive name.
    Retained background without that named relation remains for semantic QA.
    """
    if not all(axis in requested for axis in _BILLING_SCOPE_LABELS):
        return False
    positive = (
        rf'(?i:Users on (?:the )?|The )(?P<plan>{_BILLING_NAME})(?i: (?:plans?|tiers?) '
        rf'(?:have access to|has access to|can use) (?:the )?)(?P<usage_model>{_BILLING_NAME})'
        rf'(?i: usage models?)(?:, while the bill depends on CPU time for '
        rf'(?P<cpu_mode>{_BILLING_NAME})(?i: usage models?))?[.!]'
    )
    found = False
    for sentence in re.split(r'(?<=[.!?。！？])\s+|\n', source_text):
        names = _billing_names(sentence)
        if (requested['usage_model'] not in names['usage_model']
                or not re.search(_BILLING_SCOPE_LABELS['plan'], sentence, re.I)):
            continue
        match = re.fullmatch(positive, sentence.strip())
        if (_unknown_billing_scope(sentence) or match is None
                or any(names[axis] != {requested[axis]} for axis in _BILLING_SCOPE_LABELS)
                or any(match[axis] != requested[axis] for axis in _BILLING_SCOPE_LABELS)
                or match['cpu_mode'] and match['cpu_mode'] != requested['usage_model']):
            return False
        found = True
    return found


def _cpu_billing_dependency(fact, question, product):
    texts = [text for _, text in _source_strings(fact)]
    source_text = '\n'.join(dict.fromkeys(texts))
    names = _source_billing_names(fact)
    requested = _source_matched_request_scope(question, [fact])
    table = fact.qualifiers.get('table_context')
    if table:
        from packages.research.extraction.billing_rules import _cells
        # A structured row has its own complete applicability rule. Other
        # retained background and notes remain evidence for semantic QA.
        if not _matching_billing_applicability(source_text, requested) or _unknown_billing_scope(fact.quote):
            return False
        if any(values and values != {requested.get(axis)}
               for axis, values in _billing_names(fact.quote).items()):
            return False
        header, row = _cells(table[0]), _cells(fact.quote)
        if not header or not row or len(header) != len(row):
            return False
        model = requested.get('usage_model')
        if model and row[0].casefold() != model.casefold():
            return False
        for label, value in zip(header, row, strict=True):
            if not re.search(r'\bCPU\b', label, re.I):
                continue
            if (_unknown_billing_scope(label)
                    or any(values and values != {requested.get(axis)}
                           for axis, values in _billing_names(label).items())):
                continue
            if re.search(r'\b(?:free|no charge|not billed|not charged)\b|免费|不计费|不收费', value, re.I):
                continue
            if _positive_cpu_time_rate(value, label):
                return True
        # Another row, Duration column or footnote cannot override this CPU cell.
        return False
    if _unknown_billing_scope(source_text):
        return False
    if any(names[axis] and axis not in requested for axis in names):
        return False
    if all(names.values()) and not _matching_billing_applicability(source_text, requested):
        return False
    for sentence in re.split(r'(?<=[.!?。！？])\s+|\n', source_text):
        sentence_names = _billing_names(sentence)
        if _unknown_billing_scope(sentence):
            continue
        if any(values and values != {requested.get(axis)}
               for axis in names for values in [sentence_names[axis] or names[axis]]):
            continue
        if not re.search(r'\bCPU\b', sentence, re.I) or not billing_rule_text_signal(sentence):
            continue
        from packages.research.extraction.billing_rules import _RATE
        if _RATE.search(sentence) and not _positive_cpu_time_rate(sentence):
            continue
        if re.search(r'\bCPU\b.{0,100}\b(?:billed|charged)\b.{0,100}'
                     r'\bper\s+(?:(?:additional|million|billion|\d[\d,]*)\s+)*requests?\b'
                     r'|CPU[^。！？\n]{0,60}按请求计费', sentence, re.I):
            continue
        if re.search(r'\b(?:not|never|no|free|excluded|without)\b|不计费|不收费|免费|无关', sentence, re.I):
            continue
        if re.search(r'\bCPU\b[^.!?\n]{0,100}\b(?:billed|charged|fees?|costs?)\b|'
                     r'\b(?:bill|billing|price|cost|fee|charge)\b[^.!?\n]{0,60}'
                     r'\b(?:depends? on|based on|includes?)\b[^.!?\n]{0,100}\bCPU\b|'
                     r'CPU[^。！？\n]{0,50}(?:计费|收费)|(?:计费|账单)[^。！？\n]{0,50}CPU', sentence, re.I):
            return True
    return False


def _bill_input_gaps(question, views, as_of):
    """Name a usage component only when an eligible original billing rule names it."""
    observed_at = datetime.combine(as_of, time.max, tzinfo=UTC)
    source_ids = {source.id for view in views for source in view.sources
                  if source.role == 'source' and source.material_level in {'full_source', 'kb_document'}
                  and not _qualification(source, observed_at)}
    cpu_rule = any(
        _cpu_billing_dependency(fact, question, view.competitor)
        for view in views for fact in view.facts
        if fact.status == 'supported' and fact.field == 'evidence_terms' and fact.source_id in source_ids
    )
    provided = re.search(
        r'(?<![A-Za-z])CPU(?![A-Za-z])\s*(?:总用量|总使用量|总时间|total (?:usage|time))'
        r'\s*(?:为|是|为共计|共计|is|was|of|:|：)?\s*\d+(?:\.\d+)?\s*'
        r'(?:毫秒|milliseconds?|ms)(?![A-Za-z])', question, re.I,
    )
    return {'cpu_usage'} if cpu_rule and not provided else set()


def _published_cpu_table_dependency(fact, parent, question, text):
    """An exact named row supports its own CPU cell; parent text only limits it."""
    from packages.research.extraction.billing_rules import _cells, billing_table_context

    table = parent.qualifiers.get('table_context')
    if not table or fact.quote != parent.quote:
        return False
    header, row = _cells(table[0]), _cells(fact.quote)
    if not header or not row or len(header) != len(row):
        return False
    requested = _source_matched_request_scope(question, [parent])
    model = requested.get('usage_model')
    if (not model or row[0].casefold() != model.casefold()
            or not re.search(r'(?<![A-Za-z0-9_+-])' + re.escape(model)
                             + r'(?![A-Za-z0-9_+-])', text, re.I)
            or not re.search(r'\bCPU\s+(?:time|milliseconds?|seconds?)\b|'
                             r'CPU\s*(?:时间|耗时|毫秒)', text, re.I)):
        return False
    # Replay header/row/footnote completeness using the same admission grammar.
    prefix = table[0] + '\n|' + '|'.join('---' for _ in header) + '|\n'
    body = prefix + fact.quote + '\n' + '\n'.join(table[1:]) + '\n'
    if billing_table_context(body, len(prefix), len(prefix) + len(fact.quote)) != list(table):
        return False
    return any(re.search(r'\bCPU\b', label, re.I)
               and not _unknown_billing_scope(label)
               and not any(values and values != {requested.get(axis)}
                           for axis, values in _billing_names(label).items())
               and _positive_cpu_time_rate(value, label)
               and not re.search(r'\b(?:free|no charge|not billed|not charged)\b|'
                                 r'免费|不计费|不收费', value, re.I)
               for label, value in zip(header, row, strict=True))


def _published_cpu_claims(question, product, views, as_of, claims):
    """Public premises use only replayable published support, never sibling text."""
    observed_at = datetime.combine(as_of, time.max, tzinfo=UTC)
    result = []
    for claim in claims:
        if claim.competitor != product or claim.kind != 'fact' or not claim.source_span_bindings:
            continue
        view = next((view for view in views if view.dimension == claim.dimension), None)
        if view is None:
            continue
        eligible = {source.id for source in view.sources if source.role == 'source'
                    and source.material_level in {'full_source', 'kb_document'}
                    and not _qualification(source, observed_at)}
        if not set(claim.source_ids) <= eligible:
            continue
        selected = [fact for fact in view.facts if fact.id in claim.fact_ids]
        projected, reasons = projected_source_facts(claim, selected)
        boundary = SimpleNamespace(allowed_fact_ids=view.fact_ids,
            requirement=SimpleNamespace(intent='facts'), missing_fields=())
        if reasons or claim_rule_reasons(claim, view, [boundary], available_facts=view.facts):
            continue
        # The selected member and the asserted claim must both name an
        # applicable CPU-time billing dependency. Parent context only limits it.
        assertion_text = re.sub(
            r'(?<![A-Za-z0-9_+-])(' + _BILLING_NAME + r')\s*用量模式',
            lambda match: match[1] + ' usage model ', claim.text,
        )
        assertion = SimpleNamespace(quote=assertion_text, value=[assertion_text], qualifiers={})
        parents = {fact.id: fact for fact in selected}
        if (_cpu_billing_dependency(assertion, question, product)
                and any(_cpu_billing_dependency(parents[fact.id], question, product)
                        and (_published_cpu_table_dependency(
                            fact, parents[fact.id], question, claim.text)
                            if parents[fact.id].qualifiers.get('table_context')
                            else _cpu_billing_dependency(fact, question, product))
                        for fact in projected)):
            result.append(claim)
    return tuple(sorted(result, key=lambda claim: (len(claim.text), claim.id))[:1])


def _incomplete_quote_answer(question, snapshot, market, as_of, context, views, claims):
    """Missing request inputs are distinct from absent evidence or a market price."""
    labels = {
        "market": "适用市场／地区", "currency": "报价币种", "plan": "具体产品组合与套餐",
        "billing_interval": "计费周期", "tax_scope": "税费口径",
        "cpu_usage": "CPU 总用量",
        "usage_inputs": "完整用量明细及其他计费项目",
        "sku_scope": "适用 SKU／合同及实际购买范围",
        "billable_seats": "实际付费席位数量",
    }
    missing = {key for key in ("currency", "plan", "billing_interval") if key not in context}
    if not market:
        missing.add("market")
    if context.get('requested_products'):
        if not re.search(r'套餐|方案|\bplans?\b|\btiers?\b', question['question'], re.I):
            missing.add('sku_scope')
        if 'employee_count' in context and 'billable_seats' not in context:
            missing.add('billable_seats')
    is_bill = bool(re.search(r"账单|\b(?:bill|invoice)\b", question['question'], re.I))
    if is_bill:
        missing.add("usage_inputs")
        missing.update(_bill_input_gaps(question['question'], views, as_of))
        if "tax_scope" not in context:
            missing.add("tax_scope")
    if not missing:
        return None
    fields = "、".join(labels[key] for key in labels if key in missing)
    known = []
    if context.get('plan'):
        known.append('购买范围 ' + context['plan'])
    if 'duration_months' in context:
        known.append(f"购买期限 {context['duration_months']}个月")
    if 'billable_seats' in context:
        known.append(f"实际付费席位 {context['billable_seats']}个")
    if 'currency' in context:
        known.append('报价币种 ' + {'CNY': '人民币', 'USD': '美元'}.get(context['currency'], context['currency']))
    if 'tax_scope' in context:
        known.append('含税' if context['tax_scope'] == 'tax_included' else '不含税')
    known_text = '已给请求条件：' + '、'.join(known) + '。' if known else ''
    cpu_claims = (
        _published_cpu_claims(question['question'], views[0].competitor, views, as_of, claims)
        if 'cpu_usage' in missing else ()
    )
    cpu_text = ' '.join(claim.text for claim in cpu_claims)
    return {
        "question_id": question["question_id"], "question": question["question"],
        "status": "partial", "resolution": "insufficient", "conclusion": "unknown",
        "answer": known_text + cpu_text
                  + f"本次请求及已准入资料不足以核实准确的{'完整账单' if is_bill else '当前报价'}。"
                  + f"请先确认：{fields}；补齐适用的定价资料和输入后，再核验截至 {as_of.isoformat()} 的适用金额。",
        "claim_ids": tuple(claim.id for claim in cpu_claims),
        "evidence_spans": tuple(
            {'claim_id': claim.id, 'quote': claim.text} for claim in cpu_claims
        ),
        "missing_fields": tuple(sorted(missing)),
        "reason": f"server_missing_quote_inputs;as_of={as_of.isoformat()}",
        "basis_snapshot_id": snapshot.id,
    }


def server_missing_price_answers(detail, snapshot, questions, product, *,
                                 claims: Sequence[ReportClaim] = ()) -> dict[str, dict]:
    """Resolve admitted-snapshot quote gaps, without asserting market-wide absence."""
    if any(not isinstance(claim, ReportClaim) for claim in claims):
        raise TypeError('published billing claims must be ReportClaim objects')
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
        observed_at = datetime.combine(as_of, time.max, tzinfo=UTC)
        eligible_sources = {source.id for view in views for source in view.sources
                            if source.role == 'source' and source.material_level in {'full_source', 'kb_document'}
                            and not _qualification(source, observed_at)}
        originals = [fact for view in views for fact in view.facts
                     if fact.field == 'evidence_terms' and fact.status == 'supported'
                     and fact.source_id in eligible_sources]
        context.update(_source_matched_request_scope(question['question'], originals))
        incomplete = _incomplete_quote_answer(
            question, snapshot, market, as_of, context, views, claims
        )
        if incomplete is not None:
            result[question["question_id"]] = incomplete
            continue
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
            "status": "partial",
            "resolution": "insufficient",
            "conclusion": "unknown",
            "answer": f"本次已准入资料不足以核实截至 {as_of.isoformat()}、{scope}的当前报价，"
            "因此无法给出该口径的准确金额。请提供适用的当前单价、计费单位与税费依据后，再核验金额。",
            "claim_ids": (),
            "evidence_spans": (),
            "missing_fields": tuple(sorted(missing)),
            "reason": f"server_missing_current_price;as_of={as_of.isoformat()};scope={scope}",
            "basis_snapshot_id": snapshot.id,
        }
    return result
