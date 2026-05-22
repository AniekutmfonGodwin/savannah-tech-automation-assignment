from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from firefly_qa.config import Settings, UserCredentials

LOGGER = logging.getLogger(__name__)


class ApiClient:
    def __init__(
        self,
        settings: Settings,
        credentials: UserCredentials | None = None,
        *,
        auth_override: tuple[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.credentials = credentials
        self.auth_override = auth_override
        self._client = httpx.Client(timeout=settings.request_timeout_seconds)

    @property
    def identity(self) -> str:
        if self.auth_override is not None:
            return f"override:{self.auth_override[0]}"
        if self.credentials is None:
            return "no-auth"
        return self.credentials.username

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self._url(path)
        response = self._client.request(method, url, auth=self._auth(), **kwargs)
        LOGGER.debug(
            "%s %s -> %s as=%s",
            method.upper(),
            url,
            response.status_code,
            self.identity,
        )
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    def fetch_spec(self) -> dict[str, Any]:
        response = self._client.get(self.settings.spec_url)
        response.raise_for_status()
        return response.json()

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.settings.api_url}{path if path.startswith('/') else f'/{path}'}"

    def _auth(self) -> tuple[str, str] | None:
        if self.auth_override is not None:
            return self.auth_override
        if self.credentials is None:
            return None
        return (self.credentials.username, self.credentials.password)


def wait_for_service(settings: Settings, *, timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    with httpx.Client(timeout=2) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(settings.spec_url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.5)

    raise RuntimeError(f"API did not become ready at {settings.spec_url}") from last_error
