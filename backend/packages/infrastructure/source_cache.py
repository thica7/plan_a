"""Reuse captured public documents while preserving their original observation time."""

import asyncio
import hashlib
import json
import math
import secrets
import time
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

from packages.infrastructure.singleflight import SingleFlight

CACHE_POLICY = "public-source-v1"
_SOURCE_FLIGHT = SingleFlight()


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


async def _cached_capture(runtime, key, url, ttl_seconds):
    from packages.tools.evidence_fetch import EvidenceFetchResult

    stored = await runtime.get_json(key)
    try:
        data = deepcopy(stored["result"])
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
    return None


async def cached_fetch(url, fetch, *, options, runtime, ttl_seconds):
    """Share eligible local work; optional Redis remains a discardable cache."""
    from packages.tools.evidence_fetch import EvidenceFetchResult

    if (not _public_cache_url(url) or options.get("require_price_content")
            or options.get("force_refresh")):
        return await fetch()
    material = json.dumps([CACHE_POLICY, url, options, ttl_seconds], sort_keys=True)
    digest = hashlib.sha256(material.encode()).hexdigest()
    key = runtime.cache_key(CACHE_POLICY, url, options, ttl_seconds) if runtime else None

    async def capture():
        owner = secrets.token_hex(16)
        locked = False
        lock_attempted = False
        mutex = runtime is not None and hasattr(runtime, "acquire_cache_lock")
        try:
            if key:
                deadline = time.monotonic() + 1.0
                while True:
                    cached = await _cached_capture(runtime, key, url, ttl_seconds)
                    if cached is not None:
                        return cached
                    if not mutex:
                        break
                    lock_attempted = True
                    acquired = await runtime.acquire_cache_lock(key, owner, ttl_ms=30_000)
                    if acquired is True:
                        locked = True
                        break
                    # Backend failure or contention beyond this short wait degrades
                    # to a fresh fetch. A non-owner never publishes over an owner.
                    if acquired is None or time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(.01)
            if locked:
                cached = await _cached_capture(runtime, key, url, ttl_seconds)
                if cached is not None:
                    return cached
            result = await fetch()
            if not isinstance(result, EvidenceFetchResult):
                return result
            result = replace(result, captured_at=result.captured_at or datetime.now(UTC),
                             cache_hit=False)
            if key and _valid_result(result, url):
                data = asdict(result)
                data["captured_at"] = result.captured_at.isoformat()
                payload = {"policy": CACHE_POLICY, "result": data}
                if locked:
                    await runtime.publish_cache(key, owner, payload, ttl_seconds=ttl_seconds)
                elif not mutex:
                    await runtime.set_json(key, payload, ttl_seconds=ttl_seconds)
            return result
        finally:
            if lock_attempted:
                # SET may have committed even when its ACK was cancelled/lost.
                # Token comparison makes cleanup safe for busy or expired leases.
                cleanup = asyncio.create_task(runtime.release_cache_lock(key, owner))
                cancelled = False
                while True:
                    try:
                        await asyncio.shield(cleanup)
                        break
                    except asyncio.CancelledError:
                        cancelled = True
                        if cleanup.done():
                            break
                if cancelled:
                    raise asyncio.CancelledError()

    # Runtime identity isolates independent cache namespaces/configurations while
    # all Redis-off public requests share one bounded local flight.
    return await _SOURCE_FLIGHT.do((id(runtime), digest), capture)
