from __future__ import annotations


def test_missing_credentials_are_rejected(no_auth_client):
    response = no_auth_client.get("/integrations")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_invalid_credentials_are_rejected(invalid_client):
    response = invalid_client.get("/integrations")

    assert response.status_code == 401


def test_both_preloaded_users_can_authenticate(client1, client2):
    for client in (client1, client2):
        response = client.get("/integrations", params={"page": 1, "limit": 10})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
