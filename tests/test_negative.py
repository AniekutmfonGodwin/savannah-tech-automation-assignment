"""Negative tests for missing / malformed resource lookups.

Body-payload negative cases are consolidated into ``test_input_validation.py``
under a single parametrised matrix.  This module keeps the lookup-style
negative tests that don't fit that shape.
"""

from __future__ import annotations

from firefly_qa.endpoints import IntegrationsEndpoint


def test_get_unknown_integration_returns_not_found(client1) -> None:
    response = IntegrationsEndpoint(client1).get("00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_malformed_asset_id_is_bad_request_or_not_found(client1) -> None:
    response = client1.get("/assets/not-an-integer-or-uuid")
    assert response.status_code in {400, 404}
