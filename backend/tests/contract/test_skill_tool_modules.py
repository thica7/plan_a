from packages.tools import extract_facts, find_official_docs, search_review_site_queries, survey_simulator


def test_skill_allowlist_tools_have_structured_outputs() -> None:
    docs = find_official_docs(
        competitor="Acme",
        dimension="pricing",
        homepage_hint="https://acme.example",
    )
    reviews = search_review_site_queries(competitor="Acme", topic="AI coding assistant")
    interviews = survey_simulator(topic="AI coding assistant", competitor="Acme", dimension="persona")
    facts = extract_facts(
        "Acme pricing starts at $10 per seat. Acme supports API workflows.",
        dimension="pricing",
        source_id="pricing-1",
    )

    assert docs and docs[0].url == "https://acme.example/pricing"
    assert reviews.queries and "Acme" in reviews.queries[0]
    assert interviews and interviews[0].content_hash
    assert facts and facts[0].source_id == "pricing-1"
