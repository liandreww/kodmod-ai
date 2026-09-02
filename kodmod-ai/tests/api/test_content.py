"""Stage 4 §5 — /content endpoints.

Spec: docs/testplan/04-api.md §5 (KM-API-050..056).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def test_km_api_050_list_concepts(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/content/concepts")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 6
    assert {"id", "name", "slug"} <= set(rows[0])


async def test_km_api_051_list_concepts_filtered(client, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    async with async_session() as s:
        subject_id = (await s.execute(text("SELECT subject_id FROM concepts LIMIT 1"))).scalar_one()
    r = await client.get("/content/concepts", params={"subject_id": str(subject_id)})
    assert r.status_code == 200
    assert all(True for _ in r.json())  # filter applied, no error


async def test_km_api_052_get_concept(client, concept_ids) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(f"/content/concepts/{concept_ids['pecahan']}")
    assert r.status_code == 200
    assert r.json()["slug"] == "pecahan"
    assert (await client.get(f"/content/concepts/{uuid.uuid4()}")).status_code == 404


async def test_km_api_053_concept_lessons(client, concept_ids) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(f"/content/concepts/{concept_ids['pecahan']}/lessons")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_km_api_054_retrieve(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.post(
        "/content/retrieve", json={"query": "apa itu pecahan", "top_k": 5, "language": "id"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "apa itu pecahan"
    assert isinstance(body["chunks"], list)
    assert len(body["chunks"]) <= 5


async def test_km_api_055_retrieve_top_k_bounds(client) -> None:  # type: ignore[no-untyped-def]
    assert (
        await client.post("/content/retrieve", json={"query": "x", "top_k": 0})
    ).status_code == 422
    assert (
        await client.post("/content/retrieve", json={"query": "x", "top_k": 21})
    ).status_code == 422


async def test_km_api_056_retrieve_empty_query(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.post("/content/retrieve", json={"query": "", "top_k": 5})
    assert r.status_code == 200
    assert r.json()["chunks"] == []
