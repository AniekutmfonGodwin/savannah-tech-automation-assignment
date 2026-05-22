"""Property-based contract fuzz via Schemathesis (opt-in).

Run with::

    pytest -m schemathesis tests/test_contract_schemathesis.py

Schemathesis ingests the live Swagger document and generates inputs for every
operation, then asserts each response is well-formed per the declared schema.
This catches whole classes of bugs that hand-written tests miss: undeclared
500s, schema/response mismatches, undeclared status codes.

Skipped silently if the optional ``schemathesis`` dependency is not installed.
"""

from __future__ import annotations

import os

import pytest

schemathesis = pytest.importorskip(
    "schemathesis",
    reason="Install with `pip install -e .[fuzz]` to enable property-based fuzz",
)

pytestmark = [pytest.mark.schemathesis, pytest.mark.contract, pytest.mark.slow]


BASE_URL = os.getenv("FIREFLY_BASE_URL", "http://localhost:8080")
SPEC_URL = f"{BASE_URL}/swagger/doc.json"
AUTH = (os.getenv("FIREFLY_TEST1_USERNAME", "test1"), os.getenv("FIREFLY_TEST1_PASSWORD", "test123"))

schema = schemathesis.from_uri(SPEC_URL, base_url=f"{BASE_URL}/api/v1")


@schema.parametrize()
def test_api_conforms_to_openapi_contract(case) -> None:
    response = case.call(auth=AUTH, timeout=10)
    case.validate_response(response)
