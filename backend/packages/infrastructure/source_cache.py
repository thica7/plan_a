"""Reuse captured public documents while preserving their original observation time."""

import hashlib
import math
from dataclasses import asdict, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

CACHE_POLICY = "public-source-v1"


def _valid_cache_payload(data):
    if not isinstance(data, dict):
        return False
    strings = (
        "url",
        "title",
        "text",
        "content_hash",
        "fetch_method",
        "content_type",
        "source_material_level",
    )
    optional_strings = ("error", "failure_reason", "source_published_at", "source_updated_at")
    if (
        any(type(data.get(k)) is not str for k in strings)
        or any(data.get(k) is not None and type(data[k]) is not str for k in optional_strings)
        or any(
            type(data.get(k)) is not bool for k in ("ok", "advanced_fetch_attempted", "cache_hit")
        )
        or type(data.get("text_length")) is not int
        or data["text_length"] < 0
        or type(data.get("quality_score")) not in (int, float)
        or not math.isfinite(data["quality_score"])
        or not 0 <= data["quality_score"] <= 1
        or type(data.get("capture_metadata")) is not dict
    ):
        return False
    metadata = data["capture_metadata"]
    headings = metadata.get("document_headings", [])
    if not isinstance(headings, list) or any(
        not isinstance(h, (list, tuple))
        or len(h) != 2
        or type(h[0]) is not int
        or not 1 <= h[0] <= 6
        or type(h[1]) is not str
        for h in headings
    ):
        return False
    for key, item_type in (("pricing_controls", dict), ("pricing_offer_json", str)):
        values = metadata.get(key, [])
        if not isinstance(values, list) or any(type(v) is not item_type for v in values):
            return False
    return True


def _public_cache_url(url):
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and not any(
                word in parsed.path.lower()
                for word in ("pricing", "billing", "/plans", "/login", "/signin")
            )
        )
    except ValueError:
        return False


def _valid_result(result, url):
    return (
        result.ok is True
        and result.url == url
        and type(result.status_code) is int
        and 200 <= result.status_code < 300
        and result.source_material_level == "full_source"
        and isinstance(result.text, str)
        and bool(result.text.strip())
        and isinstance(result.title, str)
        and bool(result.title.strip())
        and isinstance(result.fetch_method, str)
        and "summary" not in result.fetch_method.lower()
        and result.quality_score >= 0.5
        and result.content_hash
        in {
            hashlib.sha256(result.text.encode()).hexdigest(),
            hashlib.sha256(result.text.encode()).hexdigest()[:16],
        }
    )


async def cached_fetch(url, fetch, *, options, runtime, ttl_seconds):
    from packages.tools.evidence_fetch import EvidenceFetchResult

    use_cache = _public_cache_url(url) and not options.get("require_price_content")
    key = runtime.cache_key(CACHE_POLICY, url, options, ttl_seconds) if use_cache else None
    if key:
        stored = await runtime.get_json(key)
        try:
            data = stored["result"].copy()
            if not _valid_cache_payload(data):
                raise ValueError("invalid cached capture structure")
            captured = datetime.fromisoformat(data["captured_at"])
            data["captured_at"] = captured
            candidate = EvidenceFetchResult(**data)
            age = (datetime.now(UTC) - captured).total_seconds()
            if (
                stored["policy"] == CACHE_POLICY
                and captured.tzinfo
                and 0 <= age <= ttl_seconds
                and _valid_result(candidate, url)
            ):
                return replace(candidate, cache_hit=True)
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    result = await fetch()
    if not isinstance(result, EvidenceFetchResult):
        return result
    result = replace(result, captured_at=result.captured_at or datetime.now(UTC), cache_hit=False)
    if key and _valid_result(result, url):
        data = asdict(result)
        data["captured_at"] = result.captured_at.isoformat()
        await runtime.set_json(
            key, {"policy": CACHE_POLICY, "result": data}, ttl_seconds=ttl_seconds
        )
    return result
