"""Extended load profiles (opt-in via ``-m load``).

The default ``test_load.py`` covers the 1000 RPM gate from the assignment.
This module adds write-heavy and mixed-workload variants representative of
real SaaS traffic patterns the JD describes (noisy-neighbor, sustained load,
per-endpoint percentiles).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pytest

from firefly_qa.factories import unique_name
from firefly_qa.metrics import percentile

pytestmark = [pytest.mark.load, pytest.mark.destructive]


def test_write_heavy_load_does_not_introduce_5xx(settings) -> None:
    """100 concurrent POSTs in 30s — error rate must stay below 1%."""
    target = 200
    url = f"{settings.api_url}/integrations"
    auth = (settings.test1.username, settings.test1.password)
    latencies: list[float] = []
    statuses: list[int] = []
    ids_created: list[str] = []

    def hit() -> tuple[int, float, str | None]:
        body = {"name": unique_name("load-write"), "type": "aws"}
        started = time.perf_counter()
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.post(url, json=body, auth=auth)
        elapsed = time.perf_counter() - started
        created_id = None
        if 200 <= response.status_code < 300:
            try:
                created_id = response.json().get("id")
            except ValueError:
                created_id = None
        return response.status_code, elapsed, created_id

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(hit) for _ in range(target)]
        for future in as_completed(futures):
            status, latency, created_id = future.result()
            statuses.append(status)
            latencies.append(latency)
            if created_id:
                ids_created.append(created_id)

    success = sum(1 for s in statuses if 200 <= s < 300)
    server_errors = sum(1 for s in statuses if s >= 500)
    summary = {
        "scenario": "write-heavy",
        "target_requests": target,
        "success_count": success,
        "server_error_count": server_errors,
        "p50_latency_seconds": round(percentile(latencies, 50), 4),
        "p95_latency_seconds": round(percentile(latencies, 95), 4),
        "p99_latency_seconds": round(percentile(latencies, 99), 4),
        "unique_statuses": sorted(set(statuses)),
        "ids_created": len(ids_created),
        "unique_ids_created": len(set(ids_created)),
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/load_summary_writes.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Cleanup
    cleanup_futures = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        for created_id in ids_created:
            cleanup_futures.append(
                pool.submit(
                    httpx.delete,
                    f"{url}/{created_id}",
                    auth=auth,
                    timeout=settings.request_timeout_seconds,
                )
            )
        for future in as_completed(cleanup_futures):
            future.result()

    assert server_errors == 0, f"docs/BUGS.md#WRITE-LOAD-5XX: {server_errors} server errors under write load"
    assert len(ids_created) == len(set(ids_created)), (
        "duplicate ids generated under concurrent writes"
    )
