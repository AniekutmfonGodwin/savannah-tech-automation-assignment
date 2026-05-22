from __future__ import annotations

from firefly_qa.factories import unique_name


def test_list_integrations_returns_array_when_empty(client1):
    response = client1.get("/integrations", params={"page": 1, "limit": 10})

    assert response.status_code == 200
    assert isinstance(response.json(), list), "List endpoints should return [] instead of null."


def test_integration_lifecycle_create_get_update_delete(client1, resources):
    integration = resources.create_integration(client1, integration_type="aws")

    fetched = client1.get(f"/integrations/{integration['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == integration["id"]

    updated_name = unique_name("renamed-integration")
    updated = client1.put(
        f"/integrations/{integration['id']}",
        json={"id": integration["id"], "name": updated_name},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == updated_name

    deleted = client1.delete(f"/integrations/{integration['id']}")
    assert deleted.status_code in {200, 204}

    after_delete = client1.get(f"/integrations/{integration['id']}")
    assert after_delete.status_code == 404


def test_integration_pagination_limit_is_respected(client1, resources):
    for index in range(3):
        resources.create_integration(client1, name=unique_name(f"page-{index}"))

    response = client1.get("/integrations", params={"page": 1, "limit": 2})

    assert response.status_code == 200
    assert len(response.json()) <= 2
