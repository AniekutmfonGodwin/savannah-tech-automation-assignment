"""Authentication / identity boundary tests.

These tests use raw ``httpx`` calls (not ``ApiClient``) so we can control the
``Authorization`` header byte-for-byte.  The service must consistently return
401 for every malformed credential without leaking implementation detail in the
response body.
"""

from __future__ import annotations

import base64

import httpx
import pytest


def _basic(raw: str) -> str:
    return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")


@pytest.mark.auth
@pytest.mark.parametrize(
    "header",
    [
        pytest.param(_basic(":test123"), id="empty-username"),
        pytest.param(_basic("test1:"), id="empty-password"),
        pytest.param("Basic notbase64", id="not-base64"),
        pytest.param(_basic("test1"), id="missing-colon"),
        pytest.param(_basic("TEST1:test123"), id="uppercase-username"),
        pytest.param("Bearer foo", id="bearer-not-basic"),
        pytest.param(_basic("test1:test456"), id="cross-credential-mix"),
        pytest.param(_basic("test1 :test123"), id="trailing-space-username"),
        pytest.param(_basic("test1:test123 "), id="trailing-space-password"),
    ],
)
def test_malformed_auth_returns_401(settings, header: str) -> None:
    response = httpx.get(
        f"{settings.api_url}/integrations",
        headers={"Authorization": header},
        timeout=settings.request_timeout_seconds,
    )
    assert response.status_code == 401, (
        f"Malformed auth header should be 401, got {response.status_code}. "
        f"Body: {response.text[:200]}"
    )


@pytest.mark.auth
def test_401_response_does_not_leak_implementation_details(settings) -> None:
    response = httpx.get(
        f"{settings.api_url}/integrations",
        timeout=settings.request_timeout_seconds,
    )
    body_lower = response.text.lower()
    for needle in ("panic", "goroutine", "/app/", "stack trace", "nil pointer"):
        assert needle not in body_lower, (
            f"401 body leaked implementation detail '{needle}': {response.text[:200]}"
        )


@pytest.mark.auth
def test_www_authenticate_header_advertises_basic_realm(settings) -> None:
    response = httpx.get(
        f"{settings.api_url}/integrations",
        timeout=settings.request_timeout_seconds,
    )
    assert response.status_code == 401
    challenge = response.headers.get("www-authenticate", "")
    assert challenge.lower().startswith("basic"), f"unexpected challenge: {challenge!r}"
    assert "realm=" in challenge.lower(), f"realm missing in challenge: {challenge!r}"


@pytest.mark.auth
@pytest.mark.contract
def test_swagger_spec_is_publicly_reachable(settings) -> None:
    """The Swagger document is intentionally unauthenticated so consumers can
    discover the contract before authenticating.  We pin this behaviour so any
    future change becomes a deliberate decision rather than a silent regression.
    """
    response = httpx.get(settings.spec_url, timeout=settings.request_timeout_seconds)
    assert response.status_code == 200
    assert response.json().get("swagger") == "2.0"
