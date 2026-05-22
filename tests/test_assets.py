from __future__ import annotations

from firefly_qa.factories import unique_name


def test_asset_lifecycle_create_list_get_update_delete(client1, resources):
    integration = resources.create_integration(client1)
    asset = resources.create_asset(client1, integration["id"])

    listed = client1.get(
        "/assets",
        params={"integrationId": integration["id"], "page": 1, "limit": 10},
    )
    assert listed.status_code == 200
    assert any(item["id"] == asset["id"] for item in listed.json())

    fetched = client1.get(f"/assets/{asset['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["integration_id"] == integration["id"]

    updated_name = unique_name("renamed-asset")
    updated = client1.patch(
        "/assets",
        json={
            "id": asset["id"],
            "name": updated_name,
            "description": "updated by automation",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == updated_name

    deleted = client1.delete(f"/assets/{asset['id']}")
    assert deleted.status_code == 204

    after_delete = client1.get(f"/assets/{asset['id']}")
    assert after_delete.status_code == 404


def test_assets_require_integration_id_for_list(client1):
    response = client1.get("/assets", params={"page": 1, "limit": 10})

    assert response.status_code == 400


def test_creating_asset_requires_existing_integration(client1):
    response = client1.post(
        "/assets",
        json={
            "integration_id": "does-not-exist",
            "name": unique_name("orphan-asset"),
            "description": "should not be created",
        },
    )

    assert response.status_code == 404
