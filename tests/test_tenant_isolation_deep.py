"""Tenant-isolation side-channel tests.

The straightforward cross-tenant verb×resource matrix lives in
``test_tenant_isolation.py``. This module covers the side-channels and the
filter-bypass cases that don't fit that matrix:

  * cross-tenant resource enumeration via status-code differential
  * ``tenant_id`` leakage in cross-tenant read responses
  * pagination amplification of the list leak
  * ``integrationId`` query filter being ignored on ``/assets``

Each test maps to a numbered entry in ``docs/BUGS.md`` so the report and the
failures stay in lock-step.
"""

from __future__ import annotations

import pytest

from firefly_qa.endpoints import AssetsEndpoint, IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = [pytest.mark.tenant, pytest.mark.destructive]


@pytest.fixture(scope="module")
def cross_tenant_setup(client1, client2):
    """Module-scoped: create the two-tenant fixture exactly once.

    Tests in this module only *read* from the fixture (no destructive ops),
    so sharing it avoids amplifying load on the in-memory test store.
    """
    int1 = IntegrationsEndpoint(client1).create(name=unique_name("t1-int"), integration_type="aws").json()
    int2 = IntegrationsEndpoint(client2).create(name=unique_name("t2-int"), integration_type="gcp").json()
    asset1 = AssetsEndpoint(client1).create(integration_id=int1["id"], name=unique_name("t1-asset")).json()
    asset2 = AssetsEndpoint(client2).create(integration_id=int2["id"], name=unique_name("t2-asset")).json()

    yield {
        "integration_t1": int1,
        "integration_t2": int2,
        "asset_t1": asset1,
        "asset_t2": asset2,
    }

    for client, asset_id in ((client1, asset1["id"]), (client2, asset2["id"])):
        try:
            AssetsEndpoint(client).delete(asset_id)
        except Exception:
            pass
    for client, int_id in ((client1, int1["id"]), (client2, int2["id"])):
        try:
            IntegrationsEndpoint(client).delete(int_id)
        except Exception:
            pass


def test_asset_list_filter_by_integration_id_is_applied(cross_tenant_setup, client2) -> None:
    """docs/BUGS.md #3 — ``GET /assets?integrationId=X`` must scope to that integration."""
    other_int = cross_tenant_setup["integration_t1"]
    response = AssetsEndpoint(client2).list(integration_id=other_int["id"])
    assert response.status_code in {200, 403, 404}, response.text
    if response.status_code == 200:
        for item in response.json() or []:
            assert item["integration_id"] == other_int["id"], (
                "docs/BUGS.md#3: integrationId filter is not applied; "
                f"got integration_id={item['integration_id']}"
            )
            assert item["tenant_id"] == "test2", (
                "docs/BUGS.md#1: cross-tenant row leaked via /assets list"
            )


def test_tenant_id_is_not_leaked_to_other_tenants(cross_tenant_setup, client1) -> None:
    """docs/BUGS.md #2 — cross-tenant responses must not disclose the owning tenant_id."""
    other_int = cross_tenant_setup["integration_t2"]
    response = IntegrationsEndpoint(client1).get(other_int["id"])
    if response.status_code == 200:
        leaked = response.json().get("tenant_id")
        assert leaked != "test2", (
            f"docs/BUGS.md#2: cross-tenant GET leaks tenant_id=`{leaked}` of the owning tenant"
        )


def test_resource_existence_is_not_distinguishable_via_status_code(cross_tenant_setup, client1) -> None:
    """docs/BUGS.md #2 — missing-id vs another-tenant's-id should look identical."""
    other_int_id = cross_tenant_setup["integration_t2"]["id"]
    nonexistent_id = "00000000-0000-0000-0000-000000000000"

    resp_other = IntegrationsEndpoint(client1).get(other_int_id)
    resp_missing = IntegrationsEndpoint(client1).get(nonexistent_id)
    assert resp_other.status_code == resp_missing.status_code, (
        "docs/BUGS.md#2: status differs between another tenant's id "
        f"({resp_other.status_code}) and a missing id ({resp_missing.status_code}); "
        "allows enumeration of other tenants' resource ids"
    )


def test_pagination_overflow_must_not_amplify_cross_tenant_leak(cross_tenant_setup, client1) -> None:
    """docs/BUGS.md #1i — large limit must still apply per-tenant filtering."""
    response = IntegrationsEndpoint(client1).list(page=1, limit=999_999)
    assert response.status_code == 200, response.text
    foreign = [item for item in response.json() or [] if item.get("tenant_id") != "test1"]
    assert not foreign, (
        f"docs/BUGS.md#1i: test1 sees {len(foreign)} integrations from other tenants with "
        f"?limit=999999 (sample ids: {[item['id'] for item in foreign[:5]]})"
    )
