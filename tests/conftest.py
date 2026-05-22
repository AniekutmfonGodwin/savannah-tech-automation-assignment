from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from firefly_qa.client import ApiClient, wait_for_service
from firefly_qa.config import Settings
from firefly_qa.contract import OpenAPIContract
from firefly_qa.endpoints import AssetsEndpoint, IntegrationsEndpoint
from firefly_qa.env_loader import load_settings
from firefly_qa.factories import ResourceTracker


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--env",
        action="store",
        default=None,
        help="Environment profile to load (config/environments/<name>.yaml). "
        "Defaults to FIREFLY_ENV or 'local'.",
    )


def pytest_configure(config: pytest.Config) -> None:
    # Propagate --env to FIREFLY_ENV so subprocesses (Locust, helpers) inherit it.
    cli_env = config.getoption("--env")
    if cli_env:
        os.environ["FIREFLY_ENV"] = cli_env


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Order tests so the critical tenant-isolation suites run BEFORE the
    # heavy load/concurrency/oversize-payload suites that can stress the
    # in-memory store used by the test image.  Without this ordering the
    # tenant-deep fixture occasionally hits a slow POST on a stressed store.
    priority_substrings = (
        "test_tenant_isolation_deep",  # most fragile — run first
        "test_tenant_isolation",
        "test_auth",
        "test_contract",
        "test_input_validation",
        "test_http_semantics",
    )

    def order_key(item: pytest.Item) -> int:
        nodeid = item.nodeid
        for index, prefix in enumerate(priority_substrings):
            if prefix in nodeid:
                return index
        return len(priority_substrings)

    items.sort(key=order_key)

    settings = load_settings()
    if not settings.read_only:
        return
    skip_destructive = pytest.mark.skip(reason=f"Destructive tests skipped on read-only env '{settings.env}'")
    for item in items:
        if "destructive" in item.keywords or "load" in item.keywords:
            item.add_marker(skip_destructive)


@pytest.fixture(scope="session")
def settings() -> Settings:
    resolved = load_settings()
    wait_for_service(resolved)
    return resolved


@pytest.fixture(scope="session")
def no_auth_client(settings: Settings) -> Iterator[ApiClient]:
    client = ApiClient(settings)
    yield client
    client.close()


@pytest.fixture(scope="session")
def invalid_client(settings: Settings) -> Iterator[ApiClient]:
    client = ApiClient(settings, auth_override=(settings.test1.username, "not-the-password"))
    yield client
    client.close()


@pytest.fixture(scope="session")
def client1(settings: Settings) -> Iterator[ApiClient]:
    client = ApiClient(settings, settings.test1)
    yield client
    client.close()


@pytest.fixture(scope="session")
def client2(settings: Settings) -> Iterator[ApiClient]:
    client = ApiClient(settings, settings.test2)
    yield client
    client.close()


@pytest.fixture(scope="session")
def all_tenant_clients(client1: ApiClient, client2: ApiClient) -> list[ApiClient]:
    """Parametrize-friendly list of authenticated tenant clients."""
    return [client1, client2]


@pytest.fixture(scope="session")
def contract(no_auth_client: ApiClient) -> OpenAPIContract:
    return OpenAPIContract(no_auth_client.fetch_spec())


@pytest.fixture
def integrations_endpoint(client1: ApiClient) -> IntegrationsEndpoint:
    return IntegrationsEndpoint(client1)


@pytest.fixture
def assets_endpoint(client1: ApiClient) -> AssetsEndpoint:
    return AssetsEndpoint(client1)


@pytest.fixture
def resources() -> Iterator[ResourceTracker]:
    tracker = ResourceTracker()
    try:
        yield tracker
    finally:
        tracker.cleanup()
