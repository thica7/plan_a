import pytest

from packages.research.evidence.admission import dimension_terms_present


@pytest.mark.parametrize(
    "text",
    [
        "Inviting people to selected projects",
        "An invitation to Project A does not grant access to Project B.",
        "Invite clients to the projects they need.",
        "只有邀请到该项目的人才能访问对应内容。",
    ],
)
def test_invitation_document_is_feature_evidence(text):
    assert dimension_terms_present("feature", text.casefold())


def test_generic_invitation_background_does_not_create_structured_facts():
    # This lexical gate only establishes document relevance, never an admitted fact.
    assert not dimension_terms_present(
        "feature", "welcome to our company, contact sales for details"
    )
