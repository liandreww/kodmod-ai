"""Locust load scenarios — spec: docs/testplan/08-performance.md

Scaffold only. A later session fills in the tasks (KM-PERF-001..005).
Run via the compose `locust` service:
    docker compose -p kodmod-test -f docker/docker-compose.test.yml --profile load up
then open http://localhost:8089.
"""

from __future__ import annotations

import os
import time

try:
    from locust import HttpUser, between, task
except Exception:  # pragma: no cover - locust only installed with [test]
    HttpUser = object  # type: ignore[assignment,misc]

    def task(*_a, **_k):  # type: ignore[no-redef]
        return lambda f: f

    def between(*_a, **_k):  # type: ignore[no-redef]
        return 0


_UTTERANCES = [
    "jelaskan apa itu pecahan",
    "bagaimana cara menjumlahkan pecahan berbeda penyebut",
    "apa itu pecahan senilai",
    "beri aku contoh soal pecahan",
]


class Student(HttpUser):  # type: ignore[misc,valid-type]
    wait_time = between(1, 3)

    def on_start(self) -> None:
        # TODO(KM-PERF-001): POST /student, mint JWT, set self.headers.
        self.headers = {"Authorization": "Bearer TODO"}

    @task(7)
    def tutoring_turn(self) -> None:
        body = {"text": _UTTERANCES[int(time.time()) % len(_UTTERANCES)]}
        self.client.post("/voice/text", data=body, headers=self.headers, name="POST /voice/text")

    @task(2)
    def analytics(self) -> None:
        sid = os.getenv("KODMOD_PERF_STUDENT_ID", "11111111-1111-1111-1111-111111111111")
        self.client.get(
            f"/analytics/student/{sid}", headers=self.headers, name="GET /analytics/student/:id"
        )
