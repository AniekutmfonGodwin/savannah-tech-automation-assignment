from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable
from uuid import uuid4

from firefly_qa.client import ApiClient
from firefly_qa.endpoints import AssetsEndpoint, IntegrationsEndpoint

LOGGER = logging.getLogger(__name__)


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


@dataclass
class ResourceTracker:
    """Creates resources and best-effort cleans them up at end of test.

    Delegates HTTP plumbing to the endpoint service-objects so test code reads
    in terms of domain concepts ("create an aws integration") rather than HTTP
    verbs and paths.
    """

    integrations: list[tuple[ApiClient, str]] = field(default_factory=list)
    assets: list[tuple[ApiClient, str]] = field(default_factory=list)

    def create_integration(
        self,
        client: ApiClient,
        *,
        name: str | None = None,
        integration_type: str = "aws",
    ) -> dict:
        endpoint = IntegrationsEndpoint(client)
        response = endpoint.create(
            name=name or unique_name("integration"),
            integration_type=integration_type,
        )
        response.raise_for_status()
        integration = response.json()
        self.integrations.append((client, integration["id"]))
        return integration

    def create_asset(
        self,
        client: ApiClient,
        integration_id: str,
        *,
        name: str | None = None,
        description: str = "created by automation",
    ) -> dict:
        endpoint = AssetsEndpoint(client)
        response = endpoint.create(
            integration_id=integration_id,
            name=name or unique_name("asset"),
            description=description,
        )
        response.raise_for_status()
        asset = response.json()
        self.assets.append((client, asset["id"]))
        return asset

    def track_integration(self, client: ApiClient, integration_id: str) -> None:
        """Register an externally-created integration for cleanup."""
        self.integrations.append((client, integration_id))

    def track_asset(self, client: ApiClient, asset_id: str) -> None:
        self.assets.append((client, asset_id))

    def cleanup(self) -> None:
        for client, asset_id in reversed(self.assets):
            _swallow(lambda c=client, a=asset_id: AssetsEndpoint(c).delete(a), label=f"asset {asset_id}")
        for client, integration_id in reversed(self.integrations):
            _swallow(
                lambda c=client, i=integration_id: IntegrationsEndpoint(c).delete(i),
                label=f"integration {integration_id}",
            )


def _swallow(action: Callable[[], object], *, label: str) -> None:
    try:
        action()
    except Exception as exc:
        LOGGER.debug("Best-effort cleanup of %s failed: %s", label, exc)
