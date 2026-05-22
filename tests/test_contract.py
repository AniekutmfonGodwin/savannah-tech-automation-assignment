from __future__ import annotations

import pytest

from firefly_qa.contract import parse_json_or_none
from firefly_qa.factories import unique_name


@pytest.mark.contract
def test_openapi_spec_exposes_expected_resource_surface(no_auth_client):
    spec = no_auth_client.fetch_spec()

    assert spec["swagger"] == "2.0"
    assert spec["basePath"] == "/api/v1"
    assert {"/integrations", "/integrations/{id}", "/assets", "/assets/{id}"}.issubset(
        spec["paths"]
    )


@pytest.mark.contract
def test_create_integration_status_matches_openapi_contract(client1, resources, contract):
    response = client1.post(
        "/integrations",
        json={"name": unique_name("contract-integration"), "type": "aws"},
    )
    if response.status_code < 400:
        resources.integrations.append((client1, response.json()["id"]))

    contract.assert_status_declared("post", "/integrations", response.status_code)
    contract.assert_response_schema(
        "post",
        "/integrations",
        response.status_code,
        parse_json_or_none(response),
    )


@pytest.mark.contract
def test_documented_update_integration_route_is_implemented(client1, resources):
    integration = resources.create_integration(client1)

    response = client1.put(
        "/integrations",
        json={"id": integration["id"], "name": unique_name("updated-integration")},
    )

    assert response.status_code == 200, (
        "OpenAPI documents PUT /integrations, so the route should update the integration "
        "rather than return 404."
    )
