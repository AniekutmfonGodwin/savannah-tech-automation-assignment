"""HTTP method/header/status-code semantics.

Cloud SaaS APIs are consumed by SDKs, IaC providers, and integration platforms
that depend on RFC-compliant HTTP semantics: 405 for wrong methods, 415 for
wrong content types, correct Content-Type response headers, and so on.
"""

from __future__ import annotations

import httpx
import pytest

from firefly_qa.endpoints import IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = pytest.mark.http_semantics


def test_response_content_type_is_json_for_list(client1) -> None:
    response = client1.get("/integrations")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_post_on_collection_member_must_be_405_not_404(client1, resources) -> None:
    integration = resources.create_integration(client1, name=unique_name("405-test"))
    response = client1.post(f"/integrations/{integration['id']}", json={})
    assert response.status_code == 405, (
        f"docs/BUGS.md#WRONG-METHOD-404: POST /integrations/{{id}} returned "
        f"{response.status_code}; RFC 7231 mandates 405 Method Not Allowed"
    )


def test_patch_on_integration_member_must_be_405_not_404(client1, resources) -> None:
    integration = resources.create_integration(client1, name=unique_name("405-patch"))
    response = client1.patch(f"/integrations/{integration['id']}", json={})
    assert response.status_code in {405, 501}, (
        f"docs/BUGS.md#WRONG-METHOD-404: PATCH /integrations/{{id}} returned "
        f"{response.status_code}; should be 405 (not declared) or implemented"
    )


def test_documented_put_integrations_collection_must_exist_or_be_removed(client1, contract) -> None:
    declared = contract.declared_methods("/integrations")
    if "put" not in declared:
        pytest.skip("PUT /integrations is not declared in the spec")
    response = client1.put("/integrations", json={"id": "anything", "name": "x"})
    assert response.status_code != 404, (
        "docs/BUGS.md#DOC-DRIFT: PUT /integrations is documented but returns 404 at runtime"
    )


def test_trailing_slash_redirects_to_canonical_path(settings) -> None:
    response = httpx.get(
        f"{settings.api_url}/integrations/",
        auth=(settings.test1.username, settings.test1.password),
        follow_redirects=False,
        timeout=settings.request_timeout_seconds,
    )
    assert response.status_code in {200, 301, 308}, response.text


def test_unknown_endpoint_returns_404(client1) -> None:
    response = client1.get("/does-not-exist-xyz")
    assert response.status_code == 404


def test_response_includes_no_implementation_leak_for_4xx(client1) -> None:
    response = client1.get("/integrations/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    for needle in ("panic", "goroutine", "/app/"):
        assert needle not in response.text.lower()
