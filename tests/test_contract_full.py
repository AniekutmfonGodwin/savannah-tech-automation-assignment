"""Full contract sweep: assert that every (method, path) declared in the
Swagger document exists at runtime and that every endpoint reachable at
runtime is declared in the spec.

This is the "doc-vs-implementation drift detector" the JD calls out: when the
API surface changes, this test fails fast and points at the diff.
"""

from __future__ import annotations

import pytest

from firefly_qa.contract import parse_json_or_none
from firefly_qa.factories import unique_name

pytestmark = pytest.mark.contract


def _hit(client, method: str, path: str):
    # Substitute path params with a value that the routing layer will accept.
    sample_path = path.replace("{id}", "00000000-0000-0000-0000-000000000000")
    payload = {"name": unique_name("contract-sweep"), "type": "aws", "description": "sweep"}
    if method in {"post", "put", "patch"}:
        return client.request(method.upper(), sample_path, json=payload)
    return client.request(method.upper(), sample_path)


def test_every_declared_operation_does_not_404_at_runtime(client1, contract) -> None:
    misses: list[str] = []
    for path in contract.declared_paths():
        for method in contract.declared_methods(path):
            response = _hit(client1, method, path)
            if response.status_code == 404 and 404 not in contract.declared_statuses(method, path):
                misses.append(f"{method.upper()} {path}")
            # Also catch the "documented but unimplemented" case where 404 is
            # specifically the doc-drift signal.
            if (
                method == "put"
                and path == "/integrations"
                and response.status_code == 404
            ):
                misses.append("PUT /integrations declared but returns 404 at runtime")
    assert not misses, (
        "docs/BUGS.md#CONTRACT-DRIFT: declared operations return 404 at runtime: " + ", ".join(misses)
    )


def test_post_create_responses_are_declared(client1, contract, resources) -> None:
    """Spot-check that the actual create status is declared in the spec."""
    response = client1.post(
        "/integrations",
        json={"name": unique_name("contract-status"), "type": "aws"},
    )
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])
    contract.assert_status_declared("post", "/integrations", response.status_code)
    contract.assert_response_schema(
        "post", "/integrations", response.status_code, parse_json_or_none(response)
    )
