"""Stage 4 §6 — /exercise endpoints.

Spec: docs/testplan/04-api.md §6 (KM-API-060..063).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def _seed_exercise(concept_id: str, *, audio_friendly: bool) -> str:
    from database.models import Exercise
    from database.session import async_session, init_db

    await init_db()
    eid = uuid.uuid4()
    async with async_session() as s:
        s.add(
            Exercise(
                id=eid,
                concept_id=uuid.UUID(concept_id),
                question="Soal contoh",
                question_type="mcq",
                options=[],
                correct_answer="A",
                difficulty="easy",
                is_audio_friendly=audio_friendly,
            )
        )
    return str(eid)


async def test_km_api_060_exercises_by_concept_audio_only(client, concept_ids, db_cleanup) -> None:  # type: ignore[no-untyped-def]
    cid = concept_ids["bangun-datar"]
    good = await _seed_exercise(cid, audio_friendly=True)
    bad = await _seed_exercise(cid, audio_friendly=False)
    db_cleanup.append(("exercises", good))
    db_cleanup.append(("exercises", bad))

    r = await client.get(f"/exercise/by-concept/{cid}")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert good in ids and bad not in ids


async def test_km_api_061_exercises_by_concept_empty(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(f"/exercise/by-concept/{uuid.uuid4()}")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.known_bug(
    "#7 — POST /exercise/generate imports agents.problem_generator.generate_questions_for_student "
    "which does not exist -> 500"
)
async def test_km_api_062_generate(client, student_factory, concept_ids, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.post(
        "/exercise/generate",
        headers=auth_headers(tok),
        json={"student_id": str(st.id), "concept_id": concept_ids["pecahan"], "n_questions": 3},
    )
    assert r.status_code == 200
    assert "exercises" in r.json()


async def test_km_api_063_generate_idor(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/exercise/generate",
        headers=auth_headers(tok),
        json={"student_id": str(uuid.uuid4()), "n_questions": 3},
    )
    assert r.status_code == 403
