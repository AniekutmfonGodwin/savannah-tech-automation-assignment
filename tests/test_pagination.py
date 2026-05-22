"""Pagination semantics.

Bad-input cases for ``page`` and ``limit`` (``0``, negatives, non-numeric)
are covered by the parametrised matrix in ``test_input_validation.py``.
This module keeps only the pagination-shape and off-by-one concerns.
"""

from __future__ import annotations

import pytest

from firefly_qa.endpoints import IntegrationsEndpoint
from firefly_qa.factories import unique_name

pytestmark = pytest.mark.pagination


def test_default_pagination_returns_an_array(client1, resources) -> None:
    resources.create_integration(client1, name=unique_name("default-pagination"))
    response = IntegrationsEndpoint(client1).list()
    assert response.status_code == 200
    assert isinstance(response.json(), list), "default list response should be a JSON array"


def test_list_response_exposes_pagination_metadata(client1, resources) -> None:
    """docs/BUGS.md #8b — clients must be able to tell whether another page exists.

    Accept either shape:
      * envelope body with one of: ``total`` / ``total_pages`` / ``has_next`` / ``next_page``
      * response headers ``X-Total-Count`` or ``Link``
    """
    # Create enough rows that pagination is meaningful.
    for index in range(3):
        resources.create_integration(client1, name=unique_name(f"meta-{index}"))

    response = IntegrationsEndpoint(client1).list(page=1, limit=2)
    assert response.status_code == 200

    headers_lower = {key.lower() for key in response.headers}
    header_signal = bool(headers_lower & {"x-total-count", "link", "x-page-count", "x-next-page"})

    body = response.json()
    envelope_signal = isinstance(body, dict) and bool(
        body.keys() & {"total", "total_pages", "total_count", "has_next", "next_page", "page_count"}
    )

    assert header_signal or envelope_signal, (
        "docs/BUGS.md#8b: list response has no pagination metadata. "
        f"headers={sorted(response.headers.keys())}; "
        f"body_type={type(body).__name__}; "
        f"body_preview={response.text[:200]}"
    )


def test_pagination_traverses_results_without_off_by_one(client1, resources) -> None:
    created_ids = [
        resources.create_integration(client1, name=unique_name(f"page-{i}"))["id"]
        for i in range(5)
    ]
    page1 = IntegrationsEndpoint(client1).list(page=1, limit=2).json() or []
    page2 = IntegrationsEndpoint(client1).list(page=2, limit=2).json() or []
    page3 = IntegrationsEndpoint(client1).list(page=3, limit=2).json() or []
    seen = {item["id"] for item in (page1 + page2 + page3)}
    missing = [i for i in created_ids if i not in seen]
    assert not missing, (
        f"docs/BUGS.md#pagination: items missing from paged traversal: {missing}"
    )
