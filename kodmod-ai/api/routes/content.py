"""
KODMOD AI — Content Routes
==========================

- GET  /content/concepts                  -> list concepts
- GET  /content/concepts/{id}             -> concept details
- GET  /content/concepts/{id}/lessons     -> lessons for a concept
- POST /content/retrieve                  -> RAG retrieval, teachers only

Every endpoint here requires a signed-in account.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import current_user, db_session, require_teacher
from database.models import Concept, Lesson, User
from models.content import (
    ConceptOut,
    ContentRetrieveRequest,
    ContentRetrieveResponse,
    LessonOut,
)
from rag.retriever import retrieve

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/concepts", response_model=list[ConceptOut])
async def list_concepts(
    subject_id: uuid.UUID | None = Query(None),
    session: AsyncSession = Depends(db_session),
    _: User = Depends(current_user),
) -> list[Concept]:
    """List curriculum concepts, optionally filtered by subject."""
    stmt = select(Concept)
    if subject_id:
        stmt = stmt.where(Concept.subject_id == subject_id)
    return list((await session.execute(stmt)).scalars().all())


@router.get("/concepts/{concept_id}", response_model=ConceptOut)
async def get_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    _: User = Depends(current_user),
) -> Concept:
    """Return details for a single concept by id."""
    concept = await session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Concept not found")
    return concept


@router.get("/concepts/{concept_id}/lessons", response_model=list[LessonOut])
async def lessons_for_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    _: User = Depends(current_user),
) -> list[Lesson]:
    """List the lessons that belong to a concept."""
    rows = (
        (await session.execute(select(Lesson).where(Lesson.concept_id == concept_id)))
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/retrieve", response_model=ContentRetrieveResponse)
async def retrieve_content(
    payload: ContentRetrieveRequest,
    _: User = Depends(require_teacher),
) -> ContentRetrieveResponse:
    """Run retrieval directly, so a teacher can check that an upload is searchable."""
    chunks = await retrieve(
        payload.query,
        subject_id=payload.subject_id,
        top_k=payload.top_k,
        language=payload.language,
    )
    return ContentRetrieveResponse(chunks=chunks, query=payload.query)
