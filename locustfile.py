"""Locust load scenario (bonus from the assignment).

Run with::

    pip install -e .[load]
    locust -f locustfile.py --headless -u 50 -r 10 -t 2m \
        --host http://localhost:8080 \
        --html reports/locust.html \
        --csv reports/locust

Simulates a realistic two-tenant SaaS read+write mix: 70% reads, 20% point
reads, 10% writes.  Each "user" rotates between test1 and test2 credentials
to exercise the multi-tenant code path.
"""

from __future__ import annotations

import os
import random
from uuid import uuid4

from locust import HttpUser, between, task


CREDS = [
    (
        os.getenv("FIREFLY_TEST1_USERNAME", "test1"),
        os.getenv("FIREFLY_TEST1_PASSWORD", "test123"),
    ),
    (
        os.getenv("FIREFLY_TEST2_USERNAME", "test2"),
        os.getenv("FIREFLY_TEST2_PASSWORD", "test456"),
    ),
]


class FireflyUser(HttpUser):
    wait_time = between(0.1, 0.4)
    base_path = os.getenv("FIREFLY_API_BASE_PATH", "/api/v1")

    def on_start(self) -> None:
        self.client.auth = random.choice(CREDS)
        self.created_ids: list[str] = []

    def on_stop(self) -> None:
        for resource_id in self.created_ids:
            self.client.delete(f"{self.base_path}/integrations/{resource_id}", name="delete")

    @task(7)
    def list_integrations(self) -> None:
        self.client.get(f"{self.base_path}/integrations?page=1&limit=10", name="list integrations")

    @task(2)
    def get_integration(self) -> None:
        if not self.created_ids:
            return
        resource_id = random.choice(self.created_ids)
        self.client.get(f"{self.base_path}/integrations/{resource_id}", name="get integration")

    @task(1)
    def create_integration(self) -> None:
        body = {"name": f"locust-{uuid4().hex[:10]}", "type": "aws"}
        with self.client.post(
            f"{self.base_path}/integrations",
            json=body,
            name="create integration",
            catch_response=True,
        ) as response:
            if 200 <= response.status_code < 300:
                try:
                    self.created_ids.append(response.json()["id"])
                except (ValueError, KeyError):
                    response.failure(f"unexpected create response: {response.text[:120]}")
            else:
                response.failure(f"create failed: {response.status_code}")
