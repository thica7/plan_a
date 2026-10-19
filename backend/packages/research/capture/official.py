"""Recheck a real capture against an exact reviewed product document."""
import hashlib
import re

from packages.business_intel.official_registry import (
    registered_document, registered_product, registry_snapshot,
)


def verify_registered_capture(competitor, page):
    product = registered_product(competitor)
    if product is None:
        return None
    requested = registered_document(competitor, page.requested_url)
    final = registered_document(competitor, page.final_url)
    body = page.text or page.markdown
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    title_bound = any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", page.title, re.I)
                      for name in (product.product, *product.aliases))
    provider_reader = (page.fetch_method.startswith("deepseek_web_fetch")
                       or "provider_retrieval_receipt" in page.metadata)
    reason = None
    if requested is None or final is None:
        reason = "unregistered_document_url"
    elif provider_reader and not _provider_retrieval_is_bound(page, body_hash):
        reason = "provider_retrieval_receipt_invalid"
    elif page.status != "ok" or (not provider_reader
            and (page.status_code is None or not 200 <= page.status_code < 300)):
        reason = "capture_not_successful"
    elif (page.source_material_level != "full_source" or not body.strip()
          or "summary" in page.fetch_method.casefold() or page.quality_score < .5):
        reason = "capture_material_unverified"
    elif not title_bound or re.search(r"\b(?:vs|versus|comparison|reviews?|customer stories)\b|对比|比较|客户案例", page.title, re.I):
        reason = "product_title_mismatch"
    elif page.content_hash not in {body_hash, body_hash[:16]}:
        reason = "capture_hash_mismatch"
    reviewed = requested if provider_reader else final
    return {"status": "rejected" if reason else "verified", "reason": reason,
            "product": product.product, "requested_url": page.requested_url,
            "final_url": None if provider_reader else page.final_url, "title": page.title,
            "registered_url": reviewed.url if reviewed else None,
            "reviewed_by": reviewed.reviewed_by if reviewed else None,
            "source_reviewed_at": reviewed.reviewed_at if reviewed else None,
            "registry_sha256": registry_snapshot()[1], "content_sha256": body_hash,
            "captured_at": page.captured_at.isoformat(),
            "scope": ("provider retrieval of requested reviewed document; origin HTTP status unknown; "
                      "final redirect unobserved; not semantic approval" if provider_reader else
                      "reviewed authority plus current capture integrity; not semantic approval")}


def _provider_retrieval_is_bound(page, body_hash):
    from packages.tools.deepseek_fetch import (
        DEEPSEEK_FETCH_ENDPOINT, DEEPSEEK_FETCH_METHOD, DEEPSEEK_FETCH_PROTOCOL,
    )

    receipt = page.metadata.get("provider_retrieval_receipt")
    if (not isinstance(receipt, dict) or page.fetch_method != DEEPSEEK_FETCH_METHOD
            or page.status_code is not None or page.final_url != page.requested_url
            or page.captured_at.tzinfo is None):
        return False
    expected = {
        "protocol": DEEPSEEK_FETCH_PROTOCOL, "provider": "deepseek",
        "endpoint": DEEPSEEK_FETCH_ENDPOINT, "method": "POST",
        "requested_url": page.requested_url, "title": page.title,
        "content_sha256": body_hash, "captured_at": page.captured_at.isoformat(),
        "provider_api_status": 200, "web_api_requests": 1, "web_api_successful_responses": 1,
        "source_material_level": "full_source", "origin_status": "unknown",
        "final_url_observed": False,
    }
    if any(type(receipt.get(key)) is not type(value) or receipt[key] != value
           for key, value in expected.items()):
        return False
    return all(type(page.metadata.get(key)) is type(expected[key])
               and page.metadata[key] == expected[key] for key in (
                   "provider", "endpoint", "requested_url", "content_sha256", "captured_at",
                   "provider_api_status", "web_api_requests", "web_api_successful_responses",
                   "origin_status", "final_url_observed"))
