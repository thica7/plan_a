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


def sent_source_span_id(row, text=None):
    """Choose only IDs actually present in a Writer transport fixture."""
    choices = row.get('source_span_candidates', [])
    for candidate in choices:
        path = candidate['source_path'].split('/')
        member = row['quote'] if path[0] == 'quote' else row['value']
        if len(path) == 2:
            member = member[int(path[1])]
        if isinstance(member, str):
            support = member[candidate['start']:candidate['end']]
            if text is None or text == support or text in support:
                return candidate['span_id']
    raise AssertionError('No sent complete source span supports the fixture text')
