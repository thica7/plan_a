"""Bounded query-time lexical recall planning."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tokenization import lexical_tokens

LEXICAL_VERSION = "lexical-v3"

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
    "offline": ("离线", "断网", "offline"),
    "editing": ("编辑", "editing", "edit", "edited"),
    "creation": ("创建", "create", "creates", "creating", "creation"),
    "sharing": ("分享", "共享", "share", "shares", "sharing"),
    "sync": ("同步", "sync", "synchronize", "synchronizes", "synchronization", "syncing"),
    "encryption": ("加密", "encryption", "encrypted", "encrypt"),
    "local": ("本地", "local", "locally"),
    "desktop": ("桌面", "desktop"),
    "mobile": ("移动端", "mobile"),
    "browser": ("浏览器", "browser", "browsers"),
    "incognito": ("无痕", "隐身", "incognito", "private browsing"),
    "extension": ("扩展", "插件", "extension", "extensions"),
    "settings": ("设置", "settings", "preferences"),
    "branch protection": ("分支保护", "branch protection", "protected branches"),
    "private": ("私有", "private"),
    "repository": ("仓库", "repository", "repositories", "repo"),
    "admin": ("管理员", "admin", "administrator", "administrators", "admins"),
    "free": ("免费", "free"),
    "enterprise": ("企业版", "enterprise"),
    "paid": ("付费", "paid"),
    "public": ("公开", "public"),
    "invited": ("受邀", "邀请后", "invited", "invitation"),
    "owner": ("所有者", "owner", "owners"),
    "viewer": ("查看者", "viewer", "viewers"),
    "permission": ("权限", "permission", "permissions"),
    "runtime": ("续航", "运行时间", "runtime", "battery life"),
    "charger": ("充电器", "charger", "charging", "power supply"),
}
_EN_FILLER = frozenset(
    ("what how many much is are the a an and or for does do of in on to with "
     "can could please tell me about between default need needs must all "
     "when which it its be been also use using used requires required").split()
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
    "在", "以后", "的时候", "时候", "还能", "继续", "并", "联网以后", "联网后",
    "需要哪些", "需要", "前提条件", "条件", "有什么", "哪些",
)
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")
_QUANTITY = re.compile(
    r"(?<![a-z0-9.,，/:\-])(?P<number>[+-]?(?:\d+|\.\d+)(?:\.\d+)*"
    r"(?:\s*[,，/:]\s*(?:\d+|\.\d+)(?:\.\d+)*)*)"
    r"\s*(?P<unit>whr|wh|w)(?![a-z0-9])",
    re.IGNORECASE,
)


def _pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    if phrase[0].isascii() and phrase[0].isalnum():
        escaped = r"(?<![a-z0-9])" + escaped
    if phrase[-1].isascii() and phrase[-1].isalnum():
        escaped += r"(?![a-z0-9])"
    return re.compile(escaped, re.IGNORECASE)


def _phrase(phrase: str) -> str:
    return '"' + " ".join(lexical_tokens(phrase)) + '"'


def _quantity_expressions(text: str) -> tuple[str, list[str]]:
    """Expand spelling/spacing only; keep numeric text and physical units exact."""
    groups: list[str] = []

    def replace(match: re.Match[str]) -> str:
        number, unit = match.group("number"), match.group("unit").casefold()
        if not _DECIMAL.fullmatch(number):
            return match.group()
        spellings = ("wh", "whr") if unit in {"wh", "whr"} else ("w",)
        alternatives = dict.fromkeys(
            _phrase(f"{number}{separator}{spelling}")
            for spelling in spellings for separator in ("", " ")
        )
        group = "(" + " OR ".join(alternatives) + ")"
        if group not in groups:
            groups.append(group)
        return " "

    return _QUANTITY.sub(replace, text), groups


def quantities_match(text: str, query: str) -> bool:
    """Reject decimal/token suffix collisions without changing stored tokens."""
    def quantities(value: str) -> set[tuple[str, str]]:
        return {(match.group("number"), "wh" if match.group("unit").casefold() in {"wh", "whr"} else "w")
                for match in _QUANTITY.finditer(value)
                if _DECIMAL.fullmatch(match.group("number"))}

    if any(not _DECIMAL.fullmatch(match.group("number")) for match in _QUANTITY.finditer(query)):
        return False
    required = quantities(query)
    return not required or required <= quantities(text)


def quantity_literals(text: str) -> list[str]:
    """Keep complete quantity syntax when planning queries before FTS tokenization."""
    return list(dict.fromkeys(match.group().casefold() for match in _QUANTITY.finditer(text)))


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


def query_terms(query: str, competitors: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Recognize bounded concepts without changing the shared index tokenizer."""
    text = query
    for competitor in sorted((name for name in competitors or [] if name), key=len, reverse=True):
        text = _pattern(competitor).sub(" ", text)
    text, concepts = _remove_spans(text, [
        (concept, _pattern(alias)) for concept, aliases in _ALIASES.items() for alias in aliases
    ])
    quantities = quantity_literals(text)
    text = _QUANTITY.sub(" ", text)
    literals = [term for term in lexical_tokens(_strip_question_segments(text))
                if term not in _EN_FILLER]
    return concepts, [*literals, *quantities]


@dataclass(frozen=True)
class LexicalPlan:
    original_query: str
    strict_query: str
    fallback_query: str | None
    concepts: list[str]
    literals: list[str]
    version: str
    disabled_reason: str | None
    title_query: str | None = None
    title_body_query: str | None = None


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
    topic_positions = [match.start() for _, pattern in patterns for match in pattern.finditer(text)]
    topic_positions.extend(match.start() for match in _QUANTITY.finditer(text))
    prefix = text[:min(topic_positions)] if topic_positions else ""
    prefix, _ = _quantity_expressions(prefix)
    title_terms = [term for term in lexical_tokens(_strip_question_segments(prefix))
                   if term not in _EN_FILLER]
    text, concepts = _remove_spans(text, patterns)
    text, quantities = _quantity_expressions(text)
    text = _strip_question_segments(text)
    literals = [term for term in lexical_tokens(text) if term not in _EN_FILLER]
    reason = None
    if len(concepts) + len(quantities) > 8:
        reason = "too_many_concepts"
    elif len(literals) > 12:
        # Unknown names and conditions cannot be safely relaxed merely because
        # they occur in a long sentence. Only complete known grammar runs above
        # may disappear; unsupported prose remains conservative and observable.
        reason = "too_many_literals"
    elif not concepts and not quantities and not literals:
        reason = "competitor_only" if had_competitor else "question_only"
    elif not concepts and not quantities:
        reason = "no_concepts"
    fallback = None
    title_query = title_body_query = None
    if reason is None:
        groups = []
        for concept in concepts:
            alternatives = dict.fromkeys(_phrase(alias) for alias in _ALIASES[concept])
            groups.append("(" + " OR ".join(alternatives) + ")")
        groups.extend(quantities)
        fallback = " AND ".join([*groups, *(_phrase(term) for term in literals)])
        if (title_terms and all(term.isascii() for term in title_terms)
                and any(any(char.isalpha() for char in term) for term in title_terms)
                and literals[:len(title_terms)] == title_terms):
            title_query = _phrase(" ".join(title_terms))
            title_body_query = " AND ".join([
                *groups, *(_phrase(term) for term in literals[len(title_terms):]),
            ])
    return LexicalPlan(query, strict, fallback, concepts, literals, LEXICAL_VERSION, reason,
                       title_query, title_body_query)
