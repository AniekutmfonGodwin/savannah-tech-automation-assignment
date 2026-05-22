from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class UserCredentials:
    username: str
    password: str


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_base_path: str
    spec_path: str
    request_timeout_seconds: float
    test1: UserCredentials
    test2: UserCredentials
    load_requests_per_minute: int
    load_duration_seconds: int
    env: str = "local"
    read_only: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Backwards-compatible loader that ignores YAML profiles.

        New code should use :func:`firefly_qa.env_loader.load_settings`.
        """
        return cls(
            env=_env("FIREFLY_ENV", "local"),
            base_url=_env("FIREFLY_BASE_URL", "http://localhost:8080").rstrip("/"),
            api_base_path=_env("FIREFLY_API_BASE_PATH", "/api/v1"),
            spec_path=_env("FIREFLY_SPEC_PATH", "/swagger/doc.json"),
            request_timeout_seconds=float(_env("FIREFLY_REQUEST_TIMEOUT_SECONDS", "5")),
            test1=UserCredentials(
                username=_env("FIREFLY_TEST1_USERNAME", "test1"),
                password=_env("FIREFLY_TEST1_PASSWORD", "test123"),
            ),
            test2=UserCredentials(
                username=_env("FIREFLY_TEST2_USERNAME", "test2"),
                password=_env("FIREFLY_TEST2_PASSWORD", "test456"),
            ),
            load_requests_per_minute=int(_env("FIREFLY_LOAD_RPM", "1000")),
            load_duration_seconds=int(_env("FIREFLY_LOAD_DURATION_SECONDS", "60")),
        )

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.api_base_path}"

    @property
    def spec_url(self) -> str:
        return f"{self.base_url}{self.spec_path}"


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value
