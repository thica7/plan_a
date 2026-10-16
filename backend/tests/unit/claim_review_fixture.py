"""Transport-shape fixtures, never semantic accuracy or real model evidence."""


def supported_review(claim, reason="The supplied statement and conditions are supported."):
    return {
        "claim_id": claim["id"],
        "verdict": "supported",
        "reason": reason,
        "checks": [
            {"check_id": item["check_id"], "verdict": "supported", "claim_span": claim["text"]}
            for item in claim.get("required_checks", [])
        ],
    }
