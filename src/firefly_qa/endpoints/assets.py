"""Service-object wrapper for the ``/assets`` resource."""

from __future__ import annotations

from typing import Any

import httpx

from firefly_qa.client import ApiClient

PATH = "/assets"


class AssetsEndpoint:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    @property
    def client(self) -> ApiClient:
        return self._client

    def list(
        self,
        *,
        integration_id: str | None,
        page: int | None = 1,
        limit: int | None = 10,
    ) -> httpx.Response:
        params = _drop_none({"integrationId": integration_id, "page": page, "limit": limit})
        return self._client.get(PATH, params=params)

    def create(
        self,
        *,
        integration_id: str,
        name: str,
        description: str = "created by automation",
        **extra: Any,
    ) -> httpx.Response:
        body = {
            "integration_id": integration_id,
            "name": name,
            "description": description,
            **extra,
        }
        return self._client.post(PATH, json=body)

    def get(self, asset_id: str) -> httpx.Response:
        return self._client.get(f"{PATH}/{asset_id}")

    def update(self, asset_id: str, **fields: Any) -> httpx.Response:
        fields.setdefault("id", asset_id)
        return self._client.patch(PATH, json=fields)

    def delete(self, asset_id: str) -> httpx.Response:
        return self._client.delete(f"{PATH}/{asset_id}")


def _drop_none(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None}
