"""Multi-tenant isolation tests.

Every endpoint that touches a resource id (read, update, delete, or accepts a
foreign id in the payload) must reject calls from a tenant that does not own
the resource.  Rather than write one test per (verb × resource) pair, the
cross-tenant access cases are expressed as a single parametrised matrix —
fixing the missing tenant-ownership guard fixes every case.

The few non-matrix concerns (list-level leak, existence side-channel,
pagination amplifier) live in `test_tenant_isolation_deep.py`.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

import pytest

from firefly_qa.client import ApiClient
from firefly_qa.endpoints import AssetsEndpoint, IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = [pytest.mark.tenant, pytest.mark.destructive]


class Ctx(NamedTuple):
    """Set of resources owned by `test1`, used as the target of cross-tenant probes."""

    integration_id: str
    asset_id: str


@pytest.fixture
def t1_resources(client1: ApiClient, resources) -> Ctx:
    integration = resources.create_integration(client1, name=unique_name("t1-int"))
    asset = resources.create_asset(client1, integration["id"], name=unique_name("t1-asset"))
    return Ctx(integration_id=integration["id"], asset_id=asset["id"])


# A cross-tenant probe is just "what does <intruder> do against <owner's resource>?".
# Each lambda returns the httpx.Response so the assertion is uniform.
CrossTenantOp = Callable[[ApiClient, Ctx], object]

CROSS_TENANT_OPS: list[tuple[str, CrossTenantOp]] = [
    ("integration-get",    lambda c, r: IntegrationsEndpoint(c).get(r.integration_id)),
    ("integration-delete", lambda c, r: IntegrationsEndpoint(c).delete(r.integration_id)),
    ("integration-put",    lambda c, r: IntegrationsEndpoint(c).update(r.integration_id, name="hijacked")),
    ("asset-get",          lambda c, r: AssetsEndpoint(c).get(r.asset_id)),
    ("asset-patch",        lambda c, r: AssetsEndpoint(c).update(r.asset_id, name="hijacked")),
    ("asset-delete",       lambda c, r: AssetsEndpoint(c).delete(r.asset_id)),
    (
        "asset-create-under-foreign-integration",
        lambda c, r: AssetsEndpoint(c).create(
            integration_id=r.integration_id, name=unique_name("cross-asset")
        ),
    ),
]


@pytest.mark.parametrize("label, op", CROSS_TENANT_OPS, ids=[lbl for lbl, _ in CROSS_TENANT_OPS])
def test_cross_tenant_access_is_forbidden(
    t1_resources: Ctx, client2: ApiClient, label: str, op: CrossTenantOp
) -> None:
    """docs/BUGS.md #1 — tenant ownership is not enforced on resource-scoped endpoints."""
    response = op(client2, t1_resources)
    assert response.status_code in {401, 403, 404}, (
        f"docs/BUGS.md#1: cross-tenant {label} should be rejected (401/403/404); "
        f"got {response.status_code}. Body: {response.text[:200]}"
    )


def test_integration_lists_are_scoped_to_authenticated_tenant(
    client1: ApiClient, client2: ApiClient, resources
) -> None:
    """docs/BUGS.md #1a — collection list must filter by tenant_id before pagination."""
    t1 = resources.create_integration(client1, name=unique_name("t1-list"))
    t2 = resources.create_integration(client2, name=unique_name("t2-list"), integration_type="gcp")

    t1_ids = {item["id"] for item in IntegrationsEndpoint(client1).list().json() or []}
    t2_ids = {item["id"] for item in IntegrationsEndpoint(client2).list().json() or []}

    assert t1["id"] in t1_ids and t2["id"] in t2_ids, "tenants should see their own resources"
    assert t2["id"] not in t1_ids, "docs/BUGS.md#1a: test1 sees test2's integration in the list"
    assert t1["id"] not in t2_ids, "docs/BUGS.md#1a: test2 sees test1's integration in the list"
