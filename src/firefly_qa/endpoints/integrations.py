"""Service-object wrapper for the ``/integrations`` resource.

Centralises URL templating, default payload shapes, and parameter naming so
test code reads as intent ("create an aws integration") rather than HTTP plumbing
("post /api/v1/integrations with JSON body").
"""

from __future__ import annotations

from typing import Any

import httpx

from firefly_qa.client import ApiClient

PATH = "/integrations"


class IntegrationsEndpoint:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    @property
    def client(self) -> ApiClient:
        return self._client

    def list(self, *, page: int | None = 1, limit: int | None = 10) -> httpx.Response:
        params = _drop_none({"page": page, "limit": limit})
        return self._client.get(PATH, params=params)

    def create(self, *, name: str, integration_type: str = "aws", **extra: Any) -> httpx.Response:
        body = {"name": name, "type": integration_type, **extra}
        return self._client.post(PATH, json=body)

    def get(self, integration_id: str) -> httpx.Response:
        return self._client.get(f"{PATH}/{integration_id}")

    def update(self, integration_id: str, **fields: Any) -> httpx.Response:
        fields.setdefault("id", integration_id)
        return self._client.put(f"{PATH}/{integration_id}", json=fields)

    def update_via_collection(self, **fields: Any) -> httpx.Response:
        """Hit the (documented but not implemented) ``PUT /integrations``."""
        return self._client.put(PATH, json=fields)

    def delete(self, integration_id: str) -> httpx.Response:
        return self._client.delete(f"{PATH}/{integration_id}")


def _drop_none(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None}
