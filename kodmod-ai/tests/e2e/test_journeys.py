"""Stage 6 — end-to-end user journeys (text-mode) against the containerized api.

Spec: docs/testplan/06-e2e.md (KM-E2E-001..006, 010).

The tutoring / quiz / RAG / meta-command journeys all enter through
``/voice/text`` or ``/quiz/*``, which currently 500 on ``student.profile`` (#1)
and the quiz field mismatch (#5) / unreachable scoring path (#11) — so those
journeys carry @known_bug. The analytics journey (KM-E2E-003) works today.
"""

from __future__ import annotations

import pytest

from tests._fakes.accessibility_asserts import assert_accessible

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="session"), pytest.mark.timeout(60)]


# --------------------------------------------------------------------------- #
# KM-E2E-001 — onboarding + tutoring
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 — POST /voice/text does student.profile -> 500; blocks the whole journey"
)
async def test_km_e2e_001_onboarding_tutoring(client, auth_headers) -> None:  # type: ignore[no-untyped-def]
    create = await client.post(
        "/student", json={"full_name": "Onboarding E2E", "preferred_language": "id"}
    )
    assert create.status_code == 201
    sid = create.json()["id"]
    from tests.e2e.conftest import _token

    hdr = auth_headers(_token(sid, "student"))

    r1 = await client.post(
        "/voice/text", headers=hdr, data={"text": "tolong jelaskan apa itu pecahan"}
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["response_text"] and body["audio_uri"] == ""
    assert_accessible(body["response_text"])

    r2 = await client.post(
        "/voice/text", headers=hdr, data={"text": "ulangi", "session_id": body["session_id"]}
    )
    assert r2.json()["response_text"] == body["response_text"]


# --------------------------------------------------------------------------- #
# KM-E2E-002 — full quiz cycle  (the "siap dipakai" milestone)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 / #5 / #6 / #11 — quiz start/submit and the answer->score path are broken"
)
async def test_km_e2e_002_full_quiz_cycle(
    client, student_factory, concept_ids, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    sid, tok = await student_factory()
    hdr = auth_headers(tok)

    start = await client.post(
        "/quiz/start",
        headers=hdr,
        json={
            "student_id": str(sid),
            "concept_id": concept_ids["pecahan"],
            "n_questions": 3,
            "difficulty": "easy",
        },
    )
    assert start.status_code == 200
    s = start.json()
    session_id, total = s["quiz_session_id"], s["total_questions"]
    assert total == 3

    last = None
    for _ in range(total):
        last = await client.post(
            "/quiz/submit",
            headers=hdr,
            json={"quiz_session_id": session_id, "question_id": "q", "student_answer": "A"},
        )
        assert last.status_code == 200
    assert last.json()["quiz_complete"] is True
    assert last.json()["final_summary"]

    an = await client.get(f"/analytics/student/{sid}", headers=hdr)
    assert an.json()["n_quiz_attempts"] >= 3


# --------------------------------------------------------------------------- #
# KM-E2E-003 — student analytics  (works today)
# --------------------------------------------------------------------------- #
async def test_km_e2e_003_student_analytics(
    client, student_factory, concept_ids, seed_mastery, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    sid, tok = await student_factory()
    hdr = auth_headers(tok)
    await seed_mastery(sid, {concept_ids["pecahan"]: 0.55, concept_ids["fotosintesis"]: 0.85})

    rollup = await client.get(f"/analytics/student/{sid}", headers=hdr, params={"window": "month"})
    assert rollup.status_code == 200
    r = rollup.json()
    for key in ("overall_mastery", "weak_concepts", "engagement_index", "n_sessions"):
        assert key in r

    spoken = await client.get(f"/analytics/student/{sid}/spoken", headers=hdr)
    assert spoken.status_code == 200
    body = spoken.json()
    assert isinstance(body["spoken"], str) and body["spoken"].strip()
    assert "rollup" in body
    # KM-E2E-010 — accessibility guarantees on a real produced spoken summary
    assert_accessible(body["spoken"])


# --------------------------------------------------------------------------- #
# KM-E2E-004 — teacher classroom alerts
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#20 — classroom analytics/alerts need the missing classroom_enrollment table"
)
async def test_km_e2e_004_classroom_alerts(client, teacher_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    import uuid

    _tid, tok = await teacher_factory()
    r = await client.get(f"/analytics/classroom/{uuid.uuid4()}/alerts", headers=auth_headers(tok))
    assert r.status_code == 200
    assert {"alerts", "per_student", "headline"} <= set(r.json())


# --------------------------------------------------------------------------- #
# KM-E2E-005 — RAG-grounded answer
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 — the answer step goes through /voice/text which 500s on student.profile"
)
async def test_km_e2e_005_rag_grounded(client, student_factory, concept_ids, auth_headers) -> None:  # type: ignore[no-untyped-def]
    sid, tok = await student_factory()
    hdr = auth_headers(tok)

    ret = await client.post(
        "/content/retrieve",
        json={"query": "apa definisi pecahan menurut modul", "top_k": 4, "language": "id"},
    )
    assert ret.status_code == 200  # retrieval itself works unauth today

    ans = await client.post(
        "/voice/text", headers=hdr, data={"text": "menurut modul, apa definisi pecahan?"}
    )
    assert ans.status_code == 200
    assert_accessible(ans.json()["response_text"])


# --------------------------------------------------------------------------- #
# KM-E2E-006 — meta voice commands mid-session
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug("#1 — every /voice/text turn 500s on student.profile before intent routing")
async def test_km_e2e_006_meta_commands(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    sid, tok = await student_factory()
    hdr = auth_headers(tok)

    stop = await client.post("/voice/text", headers=hdr, data={"text": "berhenti"})
    assert stop.status_code == 200
    assert stop.json()["response_text"].strip()

    helpr = await client.post("/voice/text", headers=hdr, data={"text": "bantuan"})
    assert helpr.status_code == 200
