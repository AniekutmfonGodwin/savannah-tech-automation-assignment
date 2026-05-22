"""Layered configuration loader.

Resolution order (highest precedence last):
  1. Built-in defaults (in code, mirror ``local`` profile)
  2. YAML profile at ``config/environments/<env>.yaml``
  3. ``FIREFLY_*`` environment variables
  4. ``pytest --env=<name>`` CLI flag (selects which YAML to load)

Secrets are never stored in YAML — profiles reference env var names via
``password_env`` / ``username_env`` so the same codebase can run unchanged in
local Docker, GitHub Actions, or Vault-backed CI environments.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from firefly_qa.config import Settings, UserCredentials

DEFAULT_ENV = "local"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PROJECT_ROOT / "config" / "environments"


class ConfigError(RuntimeError):
    """Raised when a profile is missing, malformed, or references unset secrets."""


def load_settings(env_name: str | None = None) -> Settings:
    """Resolve a :class:`Settings` from the layered configuration."""
    resolved_env = env_name or os.getenv("FIREFLY_ENV") or DEFAULT_ENV
    profile = _load_profile(resolved_env)
    return _materialize_settings(resolved_env, profile)


def _load_profile(env_name: str) -> dict[str, Any]:
    profile_path = PROFILES_DIR / f"{env_name}.yaml"
    if not profile_path.exists():
        raise ConfigError(
            f"Unknown environment profile '{env_name}'. "
            f"Expected file: {profile_path}. Available: {_available_profiles()}"
        )
    with profile_path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ConfigError(f"Profile {profile_path} must be a mapping at top level.")
    return loaded


def _available_profiles() -> list[str]:
    return sorted(path.stem for path in PROFILES_DIR.glob("*.yaml"))


def _materialize_settings(env_name: str, profile: dict[str, Any]) -> Settings:
    base_url = _override("FIREFLY_BASE_URL", profile.get("base_url", "http://localhost:8080")).rstrip("/")
    api_base_path = _override("FIREFLY_API_BASE_PATH", profile.get("api_base_path", "/api/v1"))
    spec_path = _override("FIREFLY_SPEC_PATH", profile.get("spec_path", "/swagger/doc.json"))
    request_timeout = float(_override("FIREFLY_REQUEST_TIMEOUT_SECONDS", str(profile.get("request_timeout_seconds", 5))))

    load_section = profile.get("load") or {}
    rpm = int(_override("FIREFLY_LOAD_RPM", str(load_section.get("requests_per_minute", 1000))))
    duration = int(_override("FIREFLY_LOAD_DURATION_SECONDS", str(load_section.get("duration_seconds", 60))))

    users_section = profile.get("users") or {}
    test1 = _resolve_user("test1", users_section.get("test1") or {}, default_username="test1", default_password="test123")
    test2 = _resolve_user("test2", users_section.get("test2") or {}, default_username="test2", default_password="test456")

    return Settings(
        env=env_name,
        base_url=base_url,
        api_base_path=api_base_path,
        spec_path=spec_path,
        request_timeout_seconds=request_timeout,
        test1=test1,
        test2=test2,
        load_requests_per_minute=rpm,
        load_duration_seconds=duration,
        read_only=bool(profile.get("read_only", False)),
    )


def _resolve_user(
    label: str,
    user: dict[str, Any],
    *,
    default_username: str,
    default_password: str,
) -> UserCredentials:
    username = _resolve_secret(
        env_key=user.get("username_env"),
        literal=user.get("username"),
        fallback=default_username,
        legacy_env=f"FIREFLY_{label.upper()}_USERNAME",
    )
    password = _resolve_secret(
        env_key=user.get("password_env"),
        literal=user.get("password"),
        fallback=default_password,
        legacy_env=f"FIREFLY_{label.upper()}_PASSWORD",
    )
    return UserCredentials(username=username, password=password)


def _resolve_secret(
    *,
    env_key: str | None,
    literal: str | None,
    fallback: str,
    legacy_env: str,
) -> str:
    # Explicit env-var reference (preferred — keeps secrets out of YAML)
    if env_key:
        value = os.getenv(env_key)
        if value:
            return value
    # Legacy direct override (e.g. FIREFLY_TEST1_PASSWORD)
    legacy = os.getenv(legacy_env)
    if legacy:
        return legacy
    # Literal value embedded in YAML (only safe for local profile)
    if literal:
        return literal
    return fallback


def _override(env_var: str, current: str) -> str:
    value = os.getenv(env_var)
    return value if value is not None and value != "" else current
