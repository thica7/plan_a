"""Provenance receipts do not manufacture a product restriction."""

from test_capability_alignment import fact

from packages.research.evidence.capabilities import capability_conditioned
from packages.research.evidence.snapshot_models import canonical_json


def test_capture_identity_is_not_a_business_condition_but_real_limits_still_are():
    scope = {'capture_id': 'capture-a', 'source_id': 'source-a', 'context_sha256': 'a' * 64}
    original = fact('Example Suite', 'Members can comment on shared documents.', slot='x',
                    qualifiers={'source_scope': scope})
    assert not capability_conditioned(original)
    restricted = original.model_copy(update={
        'qualifiers_json': canonical_json({'slot': 'x', 'source_scope': scope, 'plan': 'Summit'}),
    })
    assert capability_conditioned(restricted)
    source_condition = original.model_copy(update={
        'value_json': canonical_json([original.quote, 'Available only on paid plans.']),
    })
    assert capability_conditioned(source_condition)
