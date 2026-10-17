"""Source-local monetary meaning for prose, without creating price facts.

This intentionally accepts a small explicit allowance grammar. Ambiguous text
stays unknown and cannot acquire the allowance exception to the price audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

_CURRENCY = {'$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'CNY', '￥': 'CNY',
             '元': 'CNY', 'RMB': 'CNY'}
_BREAK = re.compile(r'[。；;!?！？\n]|(?<!\d)[.,，]|[.,，](?!\d)')
# Commas and semicolons can introduce eligibility or trial restrictions on
# the same amount. Keep them inside the condition check's sentence scope.
_SENTENCE_BREAK = re.compile(r'[。!?！？]|(?<!\d)\.|\.(?!\d)')
_GRANT = re.compile(
    r'\b(?:includes?|provides?|grants?|receives?|gets?|comes\s+with)\b|包含|提供|赠送|获赠', re.I)
_PURCHASE = re.compile(
    r'\b(?:costs?|charges?|priced?\s+at|pays?|purchase|buy|bought)\b|'
    r'费用|价格|售价|月费|年费|支付|购买|付费', re.I)
_PLAN = r'[A-Za-z][A-Za-z0-9_+\-]{0,60}'
_PLAN_PREFIX = re.compile(
    rf'\s*(?P<plan>{_PLAN})(?:\s+(?:plan|tier)|\s*套餐)?\s*'
    r'(?P<period>monthly|annually|yearly|each month|each year|每月|每年)?\s*', re.I)
_PERIOD = re.compile(
    r'\b(?:per\s+month|each\s+month|monthly|per\s+year|each\s+year|annually|yearly)\b|'
    r'/(?:month|mo|year|yr)\b|每月|每年', re.I)
_CREDIT = re.compile(
    r'^\s*(?:(?:of|in|worth)\s+|的\s*)?'
    r'(?P<unit>(?:[A-Za-z][A-Za-z0-9_-]{0,24}\s*)?credits?\b|(?:AI\s*)?(?:积分|额度))', re.I)
_UNSAFE = re.compile(
    r'ignore.{0,40}instructions|system\s+prompt|api[_ -]?key|'
    r'(?:bypass|override).{0,30}(?:guard|audit|rules?)|'
    r'忽略.{0,20}指令|系统提示|绕过.{0,20}(?:审核|规则)', re.I)
_CONDITIONAL = re.compile(
    r'\b(?:only|when|if|unless|except|requires?|eligible|provided|subject to)\b|'
    r'\bduring\s+(?:the\s+)?(?:free\s+)?trial\b|'
    r'\bfor\s+the\s+first\s+(?:[^,.;\n]{1,40}\s+)?(?:months?|years?|weeks?|days?)\b|'
    r'仅限|需要|如果|除非|条件|试用期|'
    r'前\s*(?:\d+|[一二三四五六七八九十两]+)\s*个?(?:月|周|年|天)', re.I)


@dataclass(frozen=True)
class MonetaryMention:
    kind: Literal['credit_allowance', 'purchase_price', 'unknown']
    amount: Decimal
    currency: str
    start: int
    end: int
    plan: str | None = None
    period: str | None = None
    grant_action: str | None = None
    credit_unit: str | None = None
    source_path: str = ''
    quote: str = ''

    @property
    def binding(self):
        return (self.kind, self.amount, self.currency, self.plan, self.period,
                self.grant_action, self.credit_unit)


def _plan_before_grant(prefix, pattern):
    # An explicit new subject starts its own branch. A bare "and includes"
    # may retain the subject of an immediately preceding purchase clause.
    prefix = re.sub(r'^\s*[-*•]\s+', '', prefix)
    branches = re.split(r'\band\b|并且|以及', prefix, flags=re.I)
    if len(branches) > 1 and any(
        branch.strip() and not (_GRANT.search(branch) or _PURCHASE.search(branch))
        for branch in branches[:-1]
    ):
        return None, ''
    branch = branches[-1]
    match = _PLAN_PREFIX.fullmatch(branch)
    if match:
        return match['plan'].casefold(), match['period'] or ''
    purchase = re.match(rf'\s*(?P<plan>{_PLAN})(?:\s+(?:plan|tier)|\s*套餐)?\s+', prefix, re.I)
    if purchase:
        rest = prefix[purchase.end():]
        action = _PURCHASE.match(rest)
        if action and re.search(r'\s+and\s*$', rest, re.I):
            price = re.sub(r'\s+and\s*$', '', rest[action.end():], flags=re.I).strip()
            price = _PERIOD.sub('', price).strip()
            if pattern.fullmatch(price):
                return purchase['plan'].casefold(), ''
    return None, ''


def monetary_mentions(text, pattern) -> tuple[MonetaryMention, ...]:
    """Classify each currency amount using its own sentence and action."""
    result = []
    for match in pattern.finditer(text):
        currency = (match['prefix'] or match['suffix']).upper()
        amount = Decimal((match['amount'] or match['suffix_amount']).replace(',', ''))
        if match['prefix_sign'] == '-':
            amount = -abs(amount)
        base = MonetaryMention('unknown', amount, _CURRENCY.get(currency, currency),
                               match.start(), match.end())
        start = max((item.end() for item in _BREAK.finditer(text, 0, match.start())), default=0)
        stop = next(_BREAK.finditer(text, match.end()), None)
        end = stop.start() if stop else len(text)
        sentence_start = max((item.end() for item in _SENTENCE_BREAK.finditer(
            text, 0, match.start())), default=0)
        sentence_stop = next(_SENTENCE_BREAK.finditer(text, match.end()), None)
        sentence_end = sentence_stop.start() if sentence_stop else len(text)
        sentence = text[sentence_start:sentence_end]
        base = replace(base, quote=sentence.strip())
        if _UNSAFE.search(text) or _CONDITIONAL.search(sentence):
            result.append(base)
            continue
        prefix = text[start:match.start()]
        previous = list(pattern.finditer(prefix))
        local_prefix = prefix[previous[-1].end():] if previous else prefix
        if _PURCHASE.search(local_prefix):
            result.append(replace(base, kind='purchase_price'))
            continue
        grants = list(_GRANT.finditer(local_prefix))
        grant = grants[-1] if grants else None
        if grant is None or local_prefix[grant.end():].strip():
            result.append(base)
            continue
        grant_start = (previous[-1].end() if previous else 0) + grant.start()
        plan, plan_period = _plan_before_grant(prefix[:grant_start], pattern)
        tail = re.split(r'\band\b|并且|以及', text[match.end():end], maxsplit=1, flags=re.I)[0]
        credit = _CREDIT.match(tail)
        periods = {('monthly' if re.search(r'month|/mo\b|每月', item.group(), re.I) else 'annual')
                   for item in _PERIOD.finditer(plan_period + ' ' + tail)}
        if plan is None or credit is None or len(periods) != 1 or amount < 0:
            result.append(base)
            continue
        action = grant.group().casefold()
        action = 'grant' if action in {'grant', 'grants', '赠送', '获赠'} else 'include'
        unit = re.sub(r'\s+', '', credit['unit']).casefold().removesuffix('s')
        result.append(replace(base, kind='credit_allowance', plan=plan,
                              period=next(iter(periods)), grant_action=action, credit_unit=unit))
    return tuple(result)


def source_credit_allowances(fact, pattern) -> tuple[MonetaryMention, ...]:
    """Inspect admitted content only; never source payloads or metadata fields.

    The caller must additionally require this fact in the authenticated allowed
    set and its source in the paragraph's local citations.
    """
    if fact.field != 'evidence_terms' or fact.status != 'supported' or not fact.evidence_item_ids:
        return ()
    value = fact.value
    texts = [('quote', fact.quote)]
    if isinstance(value, str):
        texts.append(('value', value))
    elif isinstance(value, list):
        texts.extend((f'value.{index}', item) for index, item in enumerate(value)
                     if isinstance(item, str))
    if any(_UNSAFE.search(text) for _, text in texts):
        return ()
    return tuple(replace(mention, source_path=path)
                 for path, text in texts for mention in monetary_mentions(text, pattern)
                 if mention.kind == 'credit_allowance')
