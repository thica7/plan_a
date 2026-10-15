"""Read adjacent rendered pricing labels; keep unselected conditions unknown."""

from __future__ import annotations

import re
import json
import hashlib

from packages.research.models import CapturedPage
from packages.business_intel.entity_resolver import product_title_matches

_PLAN = re.compile(
    r"^(Starter|Professional|Pro|Organization|Enterprise|Plus|Business|Team|Free|Standard|Premium)$", re.I
)
_SEAT = re.compile(r"^(Full|Dev|Collab) seat$", re.I)
_AMOUNT = re.compile(
    r"^(?:[$€£¥￥]\s*|(?:USD|EUR|GBP|CNY|RMB)\s*)(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(USD|EUR|GBP|CNY|RMB))?(?:\s*(?:/|per\s+)\s*(mo|month|year|yr))?$",
    re.I,
)


def rendered_price_cards(competitor: str, page: CapturedPage) -> list[dict]:
    title = page.title.casefold()
    if (
        not competitor
        or not product_title_matches(competitor, page.title, page.final_url)
        or not re.search(r"pricing|plans|价格|定价", title)
        or re.search(r"\b(?:vs|versus|compare|comparison)\b|对比|比较", title)
    ):
        return []
    text = page.text or page.markdown
    currencies = list(re.finditer(r"\bPrices? in\s+(USD|EUR|GBP|CNY|RMB)\b", text, re.I))
    currency_values = {match[1].upper() for match in currencies}
    currency = next(iter(currency_values)) if len(currency_values) == 1 else None
    currency_start = currencies[0].start() if currency else 0
    currency_scope_start = 0
    plan = seat = None
    interval = "unknown"
    ready = False
    plan_start = 0
    offset = 0
    rows = []
    last_amount_end = last_quote_start = 0
    product_section = True
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        line = raw_line.strip().lstrip("# ")
        if not line:
            continue
        if competitor.casefold() == "coda":
            product_header = re.fullmatch(r"Superhuman (Docs|Mail|Go)(?:\s*\|.*)?", line, re.I)
            if product_header:
                product_section = product_header[1].casefold() == "docs"
                currency_scope_start = offset
                plan, seat, ready = None, None, False
                continue
            if not product_section:
                continue
        if rows and re.fullmatch(r"See all features and compare plans|Plans and features|Compare features", line, re.I):
            break
        period_line = re.fullmatch(r"per (member|seat|user)\s*/\s*(month|year)", line, re.I)
        if period_line and rows and not text[last_amount_end:line_start].strip():
            rows[-1]["qualifiers"].update(
                {
                    "amount_basis": period_line[1].casefold(),
                    "amount_period": "monthly"
                    if period_line[2].casefold() == "month"
                    else "annual",
                }
            )
            rows[-1]["source_quote"] = text[last_quote_start:offset].strip()
            ready = False
            continue
        maker_line = re.fullmatch(r"per\s+Doc Maker\s*,?\s*billed (annually|monthly)", text[last_amount_end:offset].strip(), re.I) if rows else None
        if maker_line:
            interval = "annual" if maker_line[1].casefold() == "annually" else "monthly"
            rows[-1]["billing_cycle"] = interval
            rows[-1]["qualifiers"].update(amount_basis="doc_maker", billing_interval=interval)
            rows[-1]["source_quote"] = text[last_quote_start:offset].strip()
            last_amount_end = offset
            continue
        alternate = re.fullmatch(r"\$(\d+(?:\.\d+)?) when billed monthly", line, re.I)
        if (alternate and rows and rows[-1]["qualifiers"].get("amount_basis") == "doc_maker"
                and not text[last_amount_end:line_start].strip()):
            row = dict(rows[-1], qualifiers=dict(rows[-1]["qualifiers"]))
            row.update(price=line, billing_cycle="monthly", source_quote=text[last_quote_start:offset].strip())
            row["qualifiers"].update(amount=float(alternate[1]), billing_interval="monthly")
            rows.append(row)
            ready = False
            continue
        if match := _PLAN.fullmatch(line.rstrip("*")):
            plan, seat, interval, ready = match[1], None, "unknown", True
            plan_start = line_start
            continue
        if re.fullmatch(r"Monthly|Annual|Yearly", line, re.I):
            # Visible toggle labels do not establish which option is selected.
            continue
        if ready and re.fullmatch(r"Recommended|Most popular", line, re.I):
            continue
        if ready and competitor.casefold() == "confluence" and re.fullmatch(
            r"Free forever for \d+ users|Everything you need to get started|Connect work across teams", line, re.I
        ):
            continue
        if re.fullmatch(r"Billed annually|Billed yearly|Billed monthly", line, re.I):
            interval = "monthly" if line.casefold().endswith("monthly") else "annual"
            continue
        if match := _SEAT.fullmatch(line):
            seat, ready = match[1].capitalize(), bool(plan)
            continue
        match = _AMOUNT.fullmatch(line)
        if match and plan and ready:
            if competitor.casefold() == "coda":
                scoped_currencies = [c for c in currencies
                                     if c.start() >= currency_scope_start and c.end() <= line_start]
                currency_values = {c[1].upper() for c in scoped_currencies}
                currency = next(iter(currency_values)) if len(currency_values) == 1 else None
                currency_start = scoped_currencies[0].start() if currency else plan_start
            amount = float(match[1].replace(",", ""))
            period = (
                "monthly"
                if (match[3] or "").casefold() in {"mo", "month"}
                else ("annual" if match[3] else "unknown")
            )
            qualifiers = {
                "plan": plan,
                "amount": amount,
                "amount_period": period,
                "billing_interval": interval,
                "tax_scope": "unknown",
            }
            explicit_currency = re.match(r"^(USD|EUR|GBP|CNY|RMB)\b", line, re.I)
            row_currency = explicit_currency[1].upper() if explicit_currency else (match[2].upper() if match[2] else currency)
            if not explicit_currency and not match[2]:
                if line.startswith("€"):
                    row_currency = "EUR"
                elif line.startswith("£"):
                    row_currency = "GBP"
                elif line.startswith("$") and currency not in {"USD", "AUD", "CAD"}:
                    row_currency = None
                elif line.startswith(("¥", "￥")) and currency not in {"CNY", "RMB", "JPY"}:
                    row_currency = None
            if row_currency:
                qualifiers["currency"] = row_currency
            if seat:
                qualifiers["seat_type"] = seat
            start = (
                min(plan_start, currency_start)
                if currency and not explicit_currency and not match[2]
                else plan_start
            )
            rows.append(
                {
                    "tier_name": plan,
                    "price": line,
                    "billing_cycle": interval,
                    "usage_limit": "",
                    "source_quote": text[start:offset].strip(),
                    "qualifiers": qualifiers,
                }
            )
            last_amount_end, last_quote_start = offset, start
            if len(rows) >= 32:
                break
        ready = False
    from packages.tools.fetch_page import _pricing_controls
    controls = page.metadata.get('pricing_controls', [])
    controls = controls if isinstance(controls, (list, tuple)) else []
    verified_controls = [item for item in controls if isinstance(item, dict)
                         and isinstance(item.get('html'), str) and item['html']
                         and item in _pricing_controls(item['html'])]
    control_name = {'notion': 'billingInterval', 'confluence': 'billing'}.get(competitor.casefold())
    intervals = [item for item in verified_controls if item.get('checked') is True
                 and control_name and item.get('name') == control_name]
    if len(intervals) == 1:
        control = intervals[0]
        for row in rows:
            if row['qualifiers'].get('amount', 0) > 0 and row['billing_cycle'] == 'unknown':
                row['billing_cycle'] = control['interval']
                row['qualifiers'].update(billing_interval=control['interval'],
                                         billing_selection_evidence=control)
    # Structured offers supplement a matching visible card; they cannot create
    # a price, select another product, or turn a monthly display into billing.
    offers = []
    raw_offers = page.metadata.get('pricing_offer_json', [])
    for raw in (raw_offers if isinstance(raw_offers, (list, tuple)) else [])[:16]:
        if not isinstance(raw, str) or len(raw) > 20000:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else []
        if not isinstance(nodes, list):
            continue
        for product in nodes[:64]:
            if not isinstance(product, dict) or product.get('@type') != 'Product' or str(product.get('name', '')).casefold() != competitor.casefold():
                continue
            candidates = product.get('offers', [])
            if not isinstance(candidates, list):
                continue
            offers.extend(item for item in candidates[:32] if isinstance(item, dict))
    for row in rows:
        matches = []
        for offer in offers:
            spec = offer.get('priceSpecification', offer)
            if not isinstance(spec, dict) or str(offer.get('name', '')).casefold() != row['tier_name'].casefold():
                continue
            try:
                amount = float(spec.get('price'))
            except (TypeError, ValueError):
                continue
            if amount == row['qualifiers']['amount'] and re.fullmatch(r'[A-Z]{3}', str(spec.get('priceCurrency', ''))):
                matches.append(spec)
        if len(matches) != 1:
            continue
        spec = matches[0]
        duration = {'P1M': 'monthly', 'P1Y': 'annual'}.get(spec.get('billingDuration'))
        reference = spec.get('referenceQuantity')
        conflict = (duration is not None and row['qualifiers'].get('amount_period')
                    not in {None, 'unknown', duration})
        if reference is not None:
            conflict = conflict or not isinstance(reference, dict) or (
                reference.get('value') != 1
                or reference.get('unitText') != row['qualifiers'].get('amount_basis'))
        if conflict:
            row['qualifiers']['price_condition_conflict'] = 'json_ld_display_billing_or_unit_mismatch'
            continue
        if row['qualifiers'].get('currency') not in {None, spec['priceCurrency']}:
            continue
        row['qualifiers'].update(currency=spec['priceCurrency'], currency_evidence={
            'product': competitor, 'plan': row['tier_name'], 'price': spec['price'],
            'priceCurrency': spec['priceCurrency'], 'method': 'same_page_matching_json_ld_offer',
            'offer_hash': hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()})
        quantity = spec.get('eligibleQuantity', {})
        counts = [item.get('count') for item in verified_controls if item.get('name') == 'unit-count']
        if (competitor.casefold() == 'confluence' and len(counts) == 1
                and isinstance(quantity, dict) and type(quantity.get('value')) is int
                and quantity.get('unitText') == 'user' and quantity['value'] == counts[0]):
            row['qualifiers']['quoted_user_count'] = counts[0]
    return rows
