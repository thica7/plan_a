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
    reason = None
    if requested is None or final is None:
        reason = "unregistered_document_url"
    elif page.status != "ok" or page.status_code is None or not 200 <= page.status_code < 300:
        reason = "capture_not_successful"
    elif (page.source_material_level != "full_source" or not body.strip()
          or "summary" in page.fetch_method.casefold() or page.quality_score < .5):
        reason = "capture_material_unverified"
    elif not title_bound or re.search(r"\b(?:vs|versus|comparison|reviews?|customer stories)\b|对比|比较|客户案例", page.title, re.I):
        reason = "product_title_mismatch"
    elif page.content_hash not in {body_hash, body_hash[:16]}:
        reason = "capture_hash_mismatch"
    return {"status": "rejected" if reason else "verified", "reason": reason,
            "product": product.product, "requested_url": page.requested_url,
            "final_url": page.final_url, "title": page.title,
            "registered_url": final.url if final else None,
            "reviewed_by": final.reviewed_by if final else None,
            "source_reviewed_at": final.reviewed_at if final else None,
            "registry_sha256": registry_snapshot()[1], "content_sha256": body_hash,
            "captured_at": page.captured_at.isoformat(),
            "scope": "reviewed authority plus current capture integrity; not semantic approval"}
