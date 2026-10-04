"""Bounded query-time lexical recall planning."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tokenization import lexical_tokens

_ALIASES: dict[str, tuple[str, ...]] = {
    "battery": ("电池", "battery", "batteries"),
    "capacity": ("容量", "capacity", "capacities"),
    "warranty": ("保修期", "保修", "质保", "warranty", "warranties"),
    "duration": ("有效期", "期限", "时长", "period", "duration", "lasts"),
    "refund": ("退款", "refund", "refunds"),
    "shipping": ("配送", "发货", "shipping", "delivery"),
    "export": ("导出", "export", "exports", "exporting"),
    "license": ("许可证", "许可", "licensing", "license", "licenses"),
    "subscription": ("订阅", "subscription", "subscriptions"),
    "billing": ("计费", "账单", "billing", "billed"),
    "monthly": ("月付", "月费", "monthly", "per month"),
    "annual": ("年付", "年费", "annual", "annually", "yearly"),
    "pricing": ("价格", "定价", "price", "prices", "pricing"),
    "plans": ("套餐", "plan", "plans"),
    "guest": ("访客", "来宾", "guest", "guests"),
    "seat": ("席位", "seat", "seats"),
    "update": ("更新", "update", "updates"),
    "security": ("安全", "security"),
    "history": ("历史", "history"),
    "retention": ("保留", "留存", "retention", "retained"),
    "deletion": ("删除", "delete", "deleted", "deletion"),
    "handoff": ("交付", "handoff"),
    "privacy": ("隐私", "privacy"),
}
_EN_FILLER = frozenset(
    ("what how many much is are the a an and or for does do of in on to with "
     "can could please tell me about").split()
)
_ZH_FILLER = (
    "请问",
    "是什么",
    "有哪些",
    "多少",
    "多久",
    "能否",
    "是否",
    "可以",
    "支持",
    "功能",
    "如何",
    "什么",
    "差异",
    "与",
    "和",
    "的",
    "能",
    "吗",
)
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def _pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    if phrase[0].isascii() and phrase[0].isalnum():
        escaped = r"(?<![a-z0-9])" + escaped
    if phrase[-1].isascii() and phrase[-1].isalnum():
        escaped += r"(?![a-z0-9])"
    return re.compile(escaped, re.IGNORECASE)


def _phrase(phrase: str) -> str:
    return '"' + " ".join(lexical_tokens(phrase)) + '"'


def _strip_question_segments(text: str) -> str:
    fillers = sorted(_ZH_FILLER, key=len, reverse=True)

    def replace(match: re.Match[str]) -> str:
        segment = match.group()
        offset = 0
        while offset < len(segment):
            filler = next((item for item in fillers if segment.startswith(item, offset)), None)
            if filler is None:
                return segment
            offset += len(filler)
        return " "

    return _CJK_RUN.sub(replace, text)


def _remove_spans(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> tuple[str, list[str]]:
    candidates = [
        (match.start(), match.end(), name)
        for name, pattern in patterns
        for match in pattern.finditer(text)
    ]
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    for start, end, name in candidates:
        if selected and start < selected[-1][1]:
            continue
        selected.append((start, end, name))
    pieces: list[str] = []
    concepts: list[str] = []
    previous = 0
    for start, end, name in selected:
        pieces.append(text[previous:start])
        pieces.append(" ")
        if name not in concepts:
            concepts.append(name)
        previous = end
    pieces.append(text[previous:])
    return "".join(pieces), concepts


@dataclass(frozen=True)
class LexicalPlan:
    original_query: str
    strict_query: str
    fallback_query: str | None
    concepts: list[str]
    literals: list[str]
    version: str
    disabled_reason: str | None


def build_lexical_plan(query: str, competitors: list[str] | None = None) -> LexicalPlan:
    strict = " ".join(_phrase(term) for term in lexical_tokens(query))
    text = query.casefold()
    had_competitor = False
    for competitor in sorted((name for name in competitors or [] if name), key=len, reverse=True):
        text, count = _pattern(competitor).subn(" ", text)
        had_competitor = had_competitor or count > 0
    patterns = [
        (concept, _pattern(alias)) for concept, aliases in _ALIASES.items() for alias in aliases
    ]
    text, concepts = _remove_spans(text, patterns)
    text = _strip_question_segments(text)
    literals = [term for term in lexical_tokens(text) if term not in _EN_FILLER]
    reason = None
    if len(concepts) > 8:
        reason = "too_many_concepts"
    elif len(literals) > 12:
        reason = "too_many_literals"
    elif not concepts and not literals:
        reason = "competitor_only" if had_competitor else "question_only"
    elif not concepts:
        reason = "no_concepts"
    fallback = None
    if reason is None:
        groups = []
        for concept in concepts:
            alternatives = dict.fromkeys(_phrase(alias) for alias in _ALIASES[concept])
            groups.append("(" + " OR ".join(alternatives) + ")")
        groups.extend(_phrase(term) for term in literals)
        fallback = " AND ".join(groups)
    return LexicalPlan(query, strict, fallback, concepts, literals, "lexical-v1", reason)
