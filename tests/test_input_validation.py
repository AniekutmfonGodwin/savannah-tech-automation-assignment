"""Input validation / 500-on-bad-input boundary tests.

For any user-controllable input, the service must respond with a documented
4xx and a well-formed JSON body — never 500.  Several inputs currently crash
the handler; they're collected here as one parametrised matrix so a single
"add input validation to DTOs" fix flips every case green.
"""

from __future__ import annotations

from typing import Callable

import httpx
import pytest

from firefly_qa.client import ApiClient
from firefly_qa.endpoints import AssetsEndpoint, IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = [pytest.mark.input_validation, pytest.mark.negative]


SENSITIVE_NEEDLES = ("panic", "goroutine", "/app/", "stack trace", "nil pointer")


def _is_well_formed_4xx(response: httpx.Response) -> bool:
    if response.status_code >= 500:
        return False
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return False
    return not any(needle in response.text.lower() for needle in SENSITIVE_NEEDLES)


# A user-input probe is "call this endpoint with intentionally bad input".
# All probes share the same expectation: the response must NOT be a 5xx.
NoFiveHundredProbe = Callable[[ApiClient], httpx.Response]

NO_5XX_PROBES: list[tuple[str, NoFiveHundredProbe]] = [
    ("empty-body",         lambda c: c.post("/integrations", json={})),
    ("empty-name",         lambda c: IntegrationsEndpoint(c).create(name="", integration_type="aws")),
    ("missing-type",       lambda c: c.post("/integrations", json={"name": unique_name("missing-type")})),
    ("patch-missing-id",   lambda c: AssetsEndpoint(c).update("00000000-0000-0000-0000-000000000000", name="x")),
    ("page=0",             lambda c: c.get("/integrations", params={"page": 0, "limit": 10})),
    ("page=-1",            lambda c: c.get("/integrations", params={"page": -1, "limit": 10})),
    ("page=abc",           lambda c: c.get("/integrations", params={"page": "abc", "limit": 10})),
    ("limit=abc",          lambda c: c.get("/integrations", params={"page": 1, "limit": "abc"})),
    ("broken-json",        lambda c: c.post(
        "/integrations", content='{"name":"x"', headers={"Content-Type": "application/json"}
    )),
]


@pytest.mark.parametrize("label, probe", NO_5XX_PROBES, ids=[lbl for lbl, _ in NO_5XX_PROBES])
def test_user_input_does_not_return_500(client1: ApiClient, label: str, probe: NoFiveHundredProbe) -> None:
    """docs/BUGS.md #7 — malformed user input must yield a 4xx, never a 5xx."""
    response = probe(client1)
    assert response.status_code < 500, (
        f"docs/BUGS.md#7 ({label}): server returned {response.status_code} — "
        f"body: {response.text[:200]}"
    )
    assert _is_well_formed_4xx(response) or response.status_code in {200, 201, 204}, (
        f"docs/BUGS.md#7 ({label}): error response leaks implementation detail: {response.text[:200]}"
    )


def test_unknown_integration_type_must_be_rejected(client1, resources) -> None:
    """docs/BUGS.md #10 — type field must be restricted to a known enum."""
    response = IntegrationsEndpoint(client1).create(
        name=unique_name("bad-type"), integration_type="fictional-cloud"
    )
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])
    assert response.status_code in {400, 422}, (
        f"docs/BUGS.md#10: type='fictional-cloud' accepted ({response.status_code})"
    )


def test_oversize_name_must_be_capped(client1, resources) -> None:
    """docs/BUGS.md #9 — name should have a documented length cap."""
    name = "x" * 5_000
    response = IntegrationsEndpoint(client1).create(name=name, integration_type="aws")
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])
    assert response.status_code in {400, 413, 422}, (
        f"docs/BUGS.md#9: 5000-char name accepted with {response.status_code}"
    )


def test_unknown_fields_must_not_override_tenant_or_id(client1, resources) -> None:
    """docs/BUGS.md #1 (server-side ownership) — body fields must not override tenant_id or id."""
    response = IntegrationsEndpoint(client1).create(
        name=unique_name("extras"),
        integration_type="aws",
        tenant_id="test2",
        id="forced-id",
    )
    if 200 <= response.status_code < 300:
        body = response.json()
        resources.track_integration(client1, body["id"])
        assert body["tenant_id"] == "test1", (
            "docs/BUGS.md#1: tenant_id override accepted from request body"
        )
        assert body["id"] != "forced-id", (
            "docs/BUGS.md#1: id override accepted from request body"
        )


def test_wrong_content_type_must_be_rejected(client1, resources) -> None:
    """docs/BUGS.md #11 — non-JSON Content-Type must produce 415."""
    response = client1.post(
        "/integrations",
        content='{"name":"plain","type":"aws"}',
        headers={"Content-Type": "text/plain"},
    )
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])
    assert response.status_code in {400, 415}, (
        f"docs/BUGS.md#11: text/plain accepted as JSON ({response.status_code})"
    )


def test_put_integration_path_id_must_take_precedence(client1, resources) -> None:
    """docs/BUGS.md #4c — PUT path id must win over body id."""
    a = resources.create_integration(client1, name=unique_name("put-a"))
    b = resources.create_integration(client1, name=unique_name("put-b"))
    response = IntegrationsEndpoint(client1).update(a["id"], id=b["id"], name="mismatch-test")
    assert response.status_code == 200, response.text
    returned = response.json()
    assert returned["id"] == a["id"], (
        f"docs/BUGS.md#4c: PUT /integrations/<A> with body id=<B> returned resource <B> "
        f"(id={returned['id']}) instead of the path resource (id={a['id']})"
    )
