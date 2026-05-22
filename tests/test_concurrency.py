"""Concurrency and idempotency tests.

These tests exercise the in-memory map storage we inferred from binary
inspection.  Concurrency around map writes is a classic Go pitfall, and DELETE
on a missing resource should be idempotent for any reasonable REST API.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from firefly_qa.endpoints import IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = [pytest.mark.concurrency, pytest.mark.destructive]


def test_concurrent_creates_with_same_name_succeed_without_5xx(client1, resources) -> None:
    name = unique_name("concurrent")

    def _create() -> int:
        response = IntegrationsEndpoint(client1).create(name=name, integration_type="aws")
        if 200 <= response.status_code < 300:
            resources.track_integration(client1, response.json()["id"])
        return response.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(lambda _: _create(), range(5)))

    assert all(status < 500 for status in statuses), (
        f"docs/BUGS.md#CONCURRENT-5XX: concurrent POST /integrations crashed (statuses={statuses})"
    )


def test_double_delete_is_idempotent(client1) -> None:
    response = IntegrationsEndpoint(client1).create(name=unique_name("double-delete"), integration_type="aws")
    assert response.status_code in {200, 201}
    integration_id = response.json()["id"]

    first = IntegrationsEndpoint(client1).delete(integration_id)
    assert first.status_code in {200, 204}
    second = IntegrationsEndpoint(client1).delete(integration_id)
    assert second.status_code in {200, 204, 404}, (
        f"docs/BUGS.md#DELETE-IDEMPOTENCY: second DELETE returned {second.status_code}; "
        "should be 204/404 (idempotent)"
    )
