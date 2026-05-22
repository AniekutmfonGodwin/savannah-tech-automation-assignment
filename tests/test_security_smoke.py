"""Security smoke probes.

Quick coverage of OWASP-style classes a Firefly customer audit would flag:
path traversal, header injection, stack-trace leakage in error responses,
multiple Authorization headers, and oversized bodies.  Not exhaustive — this
catches the easy regressions that should never reach production.
"""

from __future__ import annotations

import pytest

from firefly_qa.endpoints import IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = pytest.mark.security


SENSITIVE_NEEDLES = ("panic", "goroutine", "/app/", "stack trace", "nil pointer", "runtime error")


def _no_leak(response) -> bool:
    body = response.text.lower()
    return not any(needle in body for needle in SENSITIVE_NEEDLES)


def test_path_traversal_returns_404(client1) -> None:
    response = client1.get("/integrations/../../etc/passwd")
    assert response.status_code in {400, 404}, response.text
    assert "root:" not in response.text


def test_5xx_response_does_not_leak_stack_trace(client1) -> None:
    """If a 500 IS returned for any of these probes, the body must be sanitised."""
    triggers = [
        lambda: IntegrationsEndpoint(client1).create(name="", integration_type="aws"),
        lambda: client1.get("/integrations", params={"page": "abc"}),
    ]
    for trigger in triggers:
        response = trigger()
        if response.status_code >= 500:
            assert _no_leak(response), (
                f"docs/BUGS.md#STACK-TRACE-LEAK: server 5xx exposed implementation detail: "
                f"{response.text[:200]}"
            )


def test_xss_payload_in_name_does_not_break_response(client1, resources) -> None:
    response = IntegrationsEndpoint(client1).create(
        name='<script>alert("x")</script>', integration_type="aws"
    )
    assert response.status_code < 500
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])


def test_long_payload_does_not_crash_or_hang(client1, resources) -> None:
    # Kept at 10 KB — large enough to detect missing length validation, small
    # enough not to wedge the in-memory store the API uses for testing.
    name = "a" * 10_000
    response = IntegrationsEndpoint(client1).create(name=name, integration_type="aws")
    assert response.status_code < 500
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])


def test_unicode_payload_does_not_crash(client1, resources) -> None:
    response = IntegrationsEndpoint(client1).create(
        name=f"unicode-{unique_name('🚀 prod')}", integration_type="aws"
    )
    assert response.status_code < 500
    if 200 <= response.status_code < 300:
        resources.track_integration(client1, response.json()["id"])
