"""
KODMOD AI — Content Routes
==========================

- GET  /content/concepts                  -> list concepts
- GET  /content/concepts/{id}             -> concept details
- GET  /content/concepts/{id}/lessons     -> lessons for a concept
- POST /content/retrieve                  -> RAG retrieval (debug / direct)
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session
from database.models import Concept, Lesson
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
    subject_id: Optional[uuid.UUID] = Query(None),
    session: AsyncSession = Depends(db_session),
) -> list[Concept]:
    stmt = select(Concept)
    if subject_id:
        stmt = stmt.where(Concept.subject_id == subject_id)
    return (await session.execute(stmt)).scalars().all()


@router.get("/concepts/{concept_id}", response_model=ConceptOut)
async def get_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
) -> Concept:
    concept = await session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Concept not found")
    return concept


@router.get("/concepts/{concept_id}/lessons", response_model=list[LessonOut])
async def lessons_for_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
) -> list[Lesson]:
    rows = (
        await session.execute(select(Lesson).where(Lesson.concept_id == concept_id))
    ).scalars().all()
    return rows


@router.post("/retrieve", response_model=ContentRetrieveResponse)
async def retrieve_content(payload: ContentRetrieveRequest) -> ContentRetrieveResponse:
    chunks = await retrieve(
        payload.query,
        top_k=payload.top_k,
        language=payload.language,
    )
    return ContentRetrieveResponse(chunks=chunks, query=payload.query)
