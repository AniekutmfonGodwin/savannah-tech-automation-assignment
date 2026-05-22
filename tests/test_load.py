from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pytest

from firefly_qa.metrics import percentile


@pytest.mark.load
def test_integrations_endpoint_handles_configured_load(settings):
    nominal_requests = settings.load_requests_per_minute * settings.load_duration_seconds / 60
    target_requests = max(1, math.ceil(nominal_requests * 1.02))
    url = f"{settings.api_url}/integrations"
    auth = (settings.test1.username, settings.test1.password)
    latencies: list[float] = []
    statuses: list[int] = []
    errors: list[str] = []
    started = time.perf_counter()

    def hit_endpoint() -> tuple[int | None, float, str | None]:
        request_started = time.perf_counter()
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds) as client:
                response = client.get(url, params={"page": 1, "limit": 10}, auth=auth)
            return response.status_code, time.perf_counter() - request_started, None
        except Exception as exc:
            return None, time.perf_counter() - request_started, str(exc)

    with ThreadPoolExecutor(max_workers=25) as pool:
        futures = []
        submit_interval = settings.load_duration_seconds / target_requests
        next_submit_at = time.perf_counter()
        for _ in range(target_requests):
            futures.append(pool.submit(hit_endpoint))
            next_submit_at += submit_interval
            sleep_for = next_submit_at - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
        for future in as_completed(futures):
            status, latency, error = future.result()
            latencies.append(latency)
            if status is not None:
                statuses.append(status)
            if error is not None:
                errors.append(error)

    elapsed = time.perf_counter() - started
    throughput_per_minute = len(latencies) / elapsed * 60
    success_count = sum(1 for status in statuses if 200 <= status < 400)
    error_rate = 1 - (success_count / len(latencies))
    p95_latency = percentile(latencies, 95)

    summary = {
        "target_rpm": settings.load_requests_per_minute,
        "duration_seconds": settings.load_duration_seconds,
        "target_requests": target_requests,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_per_minute": round(throughput_per_minute, 2),
        "success_count": success_count,
        "error_rate": round(error_rate, 4),
        "p95_latency_seconds": round(p95_latency, 4),
        "unique_statuses": sorted(set(statuses)),
        "sample_errors": errors[:5],
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/load_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    assert not errors
    assert error_rate <= 0.01
    assert throughput_per_minute >= settings.load_requests_per_minute


