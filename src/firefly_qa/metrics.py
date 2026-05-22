"""Latency and throughput helpers used by load tests."""

from __future__ import annotations

import statistics


def percentile(values: list[float], percentile: int) -> float:
    """Return the requested percentile of ``values``.

    Handles edge cases ``statistics.quantiles`` would mishandle:
      * empty input → 0.0
      * single sample → the sample itself
      * p100 → ``max(values)`` (quantiles only returns ``n-1`` items)
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    if percentile >= 100:
        return max(values)
    quantiles = statistics.quantiles(values, n=100)
    index = max(0, min(percentile - 1, len(quantiles) - 1))
    return quantiles[index]
