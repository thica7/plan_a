"""Small deterministic parser for conditions explicitly bound to one body line."""

from __future__ import annotations

import math
import re

_CURRENCIES = r"USD|CNY|RMB|EUR|GBP|JPY|AUD|CAD|HKD|SGD"
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MONEY = re.compile(
    rf"\b(?P<currency>{_CURRENCIES})\s*(?P<amount>{_NUMBER})(?![\w,.])|"
    rf"(?<![\w.+-])(?P<amount_after>{_NUMBER})\s*(?P<currency_after>{_CURRENCIES})\b",
    re.I,
)
_ANY_PRICE = re.compile(
    rf"(?:\b(?:{_CURRENCIES})\s*[-+]?\d|[$¥￥€£]\s*[-+]?\d|\d[\d,.]*\s*(?:元|{_CURRENCIES})\b)",
    re.I,
)
_TIERS = (
    r"Free|Go|Pro|Team|Teams|Business|Enterprise|Max|Plus|Edu|"
    r"标准版|高级版|基础版|旗舰版|入门版|专业版"
)


def _unique(values: list[str]) -> str | None:
    distinct = {value.strip().casefold(): value.strip() for value in values if value.strip()}
    return next(iter(distinct.values())) if len(distinct) == 1 else None


def _label_values(line: str, label: str) -> list[str]:
    return re.findall(
        rf"\b(?:{label})\s*[:=]\s*([^;；|\n]+?)(?=[;；|]|\.(?:\s|$)|$)",
        line,
        re.I,
    )


def _label(line: str, label: str) -> str | None:
    return _unique(_label_values(line, label))


def has_ambiguous_price_conditions(line: str) -> bool:
    """V1 keeps explicit negations and unselected alternatives as legacy evidence."""
    if len(list(_ANY_PRICE.finditer(line))) != 1:
        return False
    money = _MONEY.search(line)
    numeric_options = money and re.match(
        rf"\s*(?:[-/–—−‑‒]+|to\b|到|至)\s*(?:{_CURRENCIES}\s*)?\d",
        line[money.end() :],
        re.I,
    )
    labelled_options = any(
        re.search(r"\band\b|[/&]|[和及与]", value, re.I)
        for value in _label_values(
            line,
            "seat_type|tax_scope|condition|market|region|model|capacity|plan|tier|channel",
        )
    )
    named_options = re.search(
        r"\b(?:Full|Dev|Collab)(?:\s+seat)?\s*(?:and|/|&)\s*(?:Full|Dev|Collab)\b|"
        r"\b(?:tax(?:es)?\s+)?(?:included|excluded)\s*(?:and|/|&)\s*(?:included|excluded)\b",
        line,
        re.I,
    )
    return bool(
        numeric_options
        or labelled_options
        or named_options
        or re.search(r"\b(?:not|no|without|unless|excluding|or)\b|或", line, re.I)
    )


def explicit_price_conditions(line: str) -> dict[str, object]:
    """No currency inference, cross-line joining, or price arithmetic."""
    if (
        "\n" in line
        or "\r" in line
        or len(list(_ANY_PRICE.finditer(line))) != 1
        or has_ambiguous_price_conditions(line)
    ):
        return {}
    matches = list(_MONEY.finditer(line))
    if len(matches) != 1:
        return {}
    match = matches[0]
    # A signed or malformed number must not match a valid numeric substring.
    if re.search(rf"\b(?:{_CURRENCIES})\s*[-+]", line, re.I):
        return {}
    amount_text = match.group("amount") or match.group("amount_after")
    amount = float(amount_text.replace(",", ""))
    if not math.isfinite(amount) or amount < 0:
        return {}
    currency = (match.group("currency") or match.group("currency_after")).upper()
    result: dict[str, object] = {
        "amount": int(amount) if amount.is_integer() else amount,
        "currency": "CNY" if currency == "RMB" else currency,
    }
    for key, label in (
        ("market", "market|region"),
        ("model", "model"),
        ("capacity", "capacity"),
        ("condition", "condition"),
        ("channel", "channel"),
        ("offer_conditions", "offer_conditions"),
        ("shipping_scope", "shipping_scope"),
    ):
        if value := _label(line, label):
            result[key] = value
    if plan := _label(line, "plan|tier") or _unique(re.findall(rf"\b({_TIERS})\b", line, re.I)):
        result["plan"] = "Team" if plan.casefold() == "teams" else plan
    seats = _label_values(line, "seat_type")
    seats += re.findall(r"\b(Full|Dev|Collab)\s+seat\b", line, re.I)
    if not seats:
        seats += ["user" for _ in re.finditer(r"\bper\s+user\b|/user\b", line, re.I)]
        seats += ["seat" for _ in re.finditer(r"\bper\s+seat\b|/seat\b", line, re.I)]
    if seat := _unique(seats):
        result["seat_type"] = seat
    taxes = []
    if re.search(
        r"\b(?:tax(?:es)?\s+included|including\s+tax|tax_scope\s*[:=]\s*included)\b|(?<![不未])含税",
        line,
        re.I,
    ):
        taxes.append("included")
    if re.search(
        r"\b(?:excluding\s+tax|tax(?:es)?\s+excluded|tax_scope\s*[:=]\s*excluded)\b|未含税|不含税",
        line,
        re.I,
    ):
        taxes.append("excluded")
    if re.search(r"\btax_scope\s*[:=]\s*unknown\b", line, re.I):
        taxes.append("unknown")
    if tax := _unique(taxes):
        result["tax_scope"] = tax
    cycles = []
    for cycle, pattern in (
        ("monthly", r"\b(?:per\s+month|monthly)\b|/(?:month|mo)\b|每月"),
        ("annual", r"\b(?:per\s+year|annual|annually|yearly)\b|/(?:year|yr)\b|每年"),
        ("one_time", r"\bone[ -]time\b|一次性|买断"),
    ):
        if re.search(pattern, line, re.I):
            cycles.append(cycle)
    billed = re.findall(r"\b(?:billed|billing)\s+(monthly|annually|annual|yearly)\b", line, re.I)
    billed_cycles = ["monthly" if value.casefold() == "monthly" else "annual" for value in billed]
    interval = _unique(billed_cycles) if billed else _unique(cycles)
    if billed and re.search(
        r"\b(?:billed|billing)\s+[^;|.]*\b(?:and|or)\b[^;|.]*\b(?:monthly|annually|annual|yearly)\b",
        line,
        re.I,
    ):
        interval = None
    if interval:
        result["billing_interval"] = interval
    amount_period = _unique(
        [
            cycle
            for cycle, pattern in (
                ("monthly", r"\s*(?:/|per\s+)(?:month|mo)\b"),
                ("annual", r"\s*(?:/|per\s+)(?:year|yr)\b"),
            )
            if re.match(pattern, line[match.end() :], re.I)
        ]
    )
    if amount_period:
        result["amount_period"] = amount_period
    bases = []
    if re.search(r"\bsubscription\b|订阅", line, re.I) or seats:
        bases.append("subscription")
    if re.search(r"\bdevice\b|设备|硬件", line, re.I):
        bases.append("device")
    if basis := _unique(bases):
        result["price_basis"] = basis
    return result


def attach_price_conditions(rows: list[dict[str, object]], body: str) -> list[dict[str, object]]:
    result = []
    for row in rows:
        row = dict(row)
        quote = str(row.get("source_quote") or "")
        lines = [line.strip() for line in body.splitlines() if quote and quote in line]
        line = lines[0] if len(lines) == 1 else quote
        conditions = explicit_price_conditions(line) if len(lines) == 1 else {}
        if has_ambiguous_price_conditions(line):
            row["qualifiers"] = {}
            row["tier_name"] = ""
            row["billing_cycle"] = ""
        if conditions:
            row["source_quote"] = line
            money = _MONEY.search(line)
            # Keep the display amount/period as an actual contiguous source span.
            suffix = re.match(
                r"\s*(?:/|per\s+)(?:month|mo|year|yr|user|seat)\b", line[money.end() :], re.I
            )
            row["price"] = line[money.start() : money.end() + (suffix.end() if suffix else 0)]
            row["qualifiers"] = conditions
            row["market"] = conditions.get("market")
            row["tier_name"] = conditions.get("plan", "")
            row["billing_cycle"] = conditions.get("billing_interval", "")
        result.append(row)
    return result
