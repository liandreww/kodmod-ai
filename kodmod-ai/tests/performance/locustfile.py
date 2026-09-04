"""Locust load scenarios — spec: docs/testplan/08-performance.md §1.

Targets the host ``api`` process (``scripts/serve_test_api``) on :8000. Run via
the compose ``locust`` service, which points ``--host`` at
``http://host.docker.internal:8000``:

    docker compose -p kodmod-test -f docker/docker-compose.test.yml --profile load up locust
    # open http://localhost:8089

or headless for a baseline capture:

    locust -f tests/performance/locustfile.py --host http://localhost:8000 \
        --headless -u 100 -r 10 -t 10m \
        --json > docs/testplan/baselines/locust-mixed.json

Each simulated user creates its own student via ``POST /student`` on start and
mints a matching JWT locally, so the run needs no pre-seeded accounts — only
``JWT_SECRET`` (env, defaults to the test secret) to sign with.

Weights encode KM-PERF-005's realistic mix: ~70 % tutoring, ~20 % analytics,
~10 % quiz. KM-PERF-001..004 are the same tasks run in isolation with
``--tags tutoring`` / ``analytics`` / ``quiz`` / ``retrieve``.
"""

from __future__ import annotations

import os
import time
import uuid

try:
    import jwt as _pyjwt
    from locust import HttpUser, between, events, tag, task
except Exception:  # pragma: no cover - locust only present with the [test] extra
    HttpUser = object  # type: ignore[assignment,misc]

    def task(*_a, **_k):  # type: ignore[no-redef]
        return lambda f: f

    def tag(*_a, **_k):  # type: ignore[no-redef]
        return lambda f: f

    def between(*_a, **_k):  # type: ignore[no-redef]
        return 0

    events = None  # type: ignore[assignment]
    _pyjwt = None  # type: ignore[assignment]


JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-not-for-prod-0123456789abcdef")
JWT_ALG = os.environ.get("JWT_ALG", "HS256")

_UTTERANCES = [
    "jelaskan apa itu pecahan",
    "bagaimana cara menjumlahkan pecahan berbeda penyebut",
    "apa itu pecahan senilai",
    "beri aku contoh soal pecahan",
    "menurut modul, apa definisi pecahan",
]


def _mint_token(sub: str, role: str = "student") -> str:
    now = int(time.time())
    return _pyjwt.encode(
        {"sub": sub, "role": role, "iat": now, "exp": now + 3600}, JWT_SECRET, algorithm=JWT_ALG
    )


class Student(HttpUser):  # type: ignore[misc,valid-type]
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.turn = 0
        self.concept_id: str | None = None
        r = self.client.post(
            "/student",
            json={"full_name": "Locust Student", "preferred_language": "id"},
            name="POST /student (setup)",
        )
        if r.status_code == 201:
            self.student_id = r.json()["id"]
        else:  # fall back to a random id so the run still exercises the auth path
            self.student_id = str(uuid.uuid4())
        self.headers = {"Authorization": f"Bearer {_mint_token(self.student_id)}"}

        c = self.client.get("/content/concepts", name="GET /content/concepts (setup)")
        if c.status_code == 200 and c.json():
            self.concept_id = c.json()[0]["id"]

    # -- KM-PERF-001 -------------------------------------------------------
    @tag("tutoring")
    @task(7)
    def tutoring_turn(self) -> None:
        self.turn += 1
        self.client.post(
            "/voice/text",
            data={"text": _UTTERANCES[self.turn % len(_UTTERANCES)]},
            headers=self.headers,
            name="POST /voice/text",
        )

    # -- KM-PERF-003 -----------------------------------------------------
    @tag("analytics")
    @task(2)
    def analytics_read(self) -> None:
        self.client.get(
            f"/analytics/student/{self.student_id}",
            headers=self.headers,
            name="GET /analytics/student/:id",
        )

    # -- KM-PERF-004 -----------------------------------------------------
    @tag("retrieve")
    @task(2)
    def content_retrieve(self) -> None:
        self.client.post(
            "/content/retrieve",
            json={"query": _UTTERANCES[self.turn % len(_UTTERANCES)], "top_k": 4, "language": "id"},
            name="POST /content/retrieve",
        )

    # -- KM-PERF-002 -----------------------------------------------------
    @tag("quiz")
    @task(1)
    def quiz_flow(self) -> None:
        if not self.concept_id:
            return
        with self.client.post(
            "/quiz/start",
            json={
                "student_id": self.student_id,
                "concept_id": self.concept_id,
                "n_questions": 3,
                "difficulty": "easy",
            },
            headers=self.headers,
            name="POST /quiz/start",
            catch_response=True,
        ) as start:
            if start.status_code != 200:
                start.failure(f"start {start.status_code}")
                return
            session_id = start.json().get("quiz_session_id")
        for _ in range(3):
            self.client.post(
                "/quiz/submit",
                json={
                    "quiz_session_id": session_id,
                    "question_id": "q",
                    "student_answer": "A",
                },
                headers=self.headers,
                name="POST /quiz/submit",
            )


if events is not None:

    @events.quitting.add_listener
    def _assert_slos(environment, **_kw) -> None:  # pragma: no cover - locust runtime hook
        """Fail the headless run if the aggregate SLOs regress badly.

        Placeholder ceilings for a 2 vCPU CI box (README §1.2); tighten against
        docs/testplan/baselines/ once the first real baseline is captured.
        """
        stats = environment.stats.total
        if stats.num_requests == 0:
            return
        fail_ratio = stats.num_failures / stats.num_requests
        p95 = stats.get_response_time_percentile(0.95)
        if fail_ratio > 0.01:
            environment.process_exit_code = 1
        if p95 and p95 > 3000:
            environment.process_exit_code = 1
