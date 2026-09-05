"""
KODMOD AI — Subjects and Curriculum Documents
=============================================

Reading subjects and concepts is open to any signed-in account: the student's
chat needs the list to offer a subject picker. Creating, editing, and uploading
require the teacher role.

Uploads are ingested in the background. `POST /subjects/{id}/documents` returns
202 with `status="processing"` and the client polls the document list, because
chunking plus embedding a textbook chapter takes far longer than a request
should be held open.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import current_user, db_session, require_teacher
from api.utils.uploads import delete_upload, save_upload, validate_suffix
from database.models import Concept, Document, Subject, User
from database.session import async_session
from models.content import ConceptOut, ConceptWrite, DocumentOut, SubjectOut, SubjectWrite

log = logging.getLogger(__name__)
router = APIRouter(tags=["subjects"])

# Documents get their own router mounted at /documents. Keeping the delete on
# the subjects router would put it at /subjects/documents/{id}, which the
# /subjects/{subject_id} route would swallow first.
documents_router = APIRouter(tags=["documents"])


async def _subject_or_404(session: AsyncSession, subject_id: uuid.UUID) -> Subject:
    subject = await session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such subject.")
    return subject


async def _decorate(session: AsyncSession, subjects: list[Subject]) -> list[SubjectOut]:
    """Attach concept and document counts in two queries rather than 2N."""
    if not subjects:
        return []
    ids = [s.id for s in subjects]
    concepts = dict(
        (
            await session.execute(
                select(Concept.subject_id, func.count())
                .where(Concept.subject_id.in_(ids))
                .group_by(Concept.subject_id)
            )
        ).all()
    )
    documents = dict(
        (
            await session.execute(
                select(Document.subject_id, func.count())
                .where(Document.subject_id.in_(ids), Document.status == "ready")
                .group_by(Document.subject_id)
            )
        ).all()
    )
    out = []
    for s in subjects:
        item = SubjectOut.model_validate(s)
        item.n_concepts = concepts.get(s.id, 0)
        item.n_documents = documents.get(s.id, 0)
        out.append(item)
    return out


# ---------------------------------------------------------------- read --
@router.get("", response_model=list[SubjectOut])
async def list_subjects(
    _: User = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> list[SubjectOut]:
    """Every subject, with its concept and indexed-document counts."""
    subjects = list((await session.execute(select(Subject).order_by(Subject.name))).scalars().all())
    return await _decorate(session, subjects)


@router.get("/{subject_id}", response_model=SubjectOut)
async def get_subject(
    subject_id: uuid.UUID,
    _: User = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> SubjectOut:
    """One subject."""
    subject = await _subject_or_404(session, subject_id)
    return (await _decorate(session, [subject]))[0]


@router.get("/{subject_id}/concepts", response_model=list[ConceptOut])
async def list_concepts(
    subject_id: uuid.UUID,
    _: User = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> list[Concept]:
    """The concepts taught in this subject."""
    await _subject_or_404(session, subject_id)
    stmt = select(Concept).where(Concept.subject_id == subject_id).order_by(Concept.name)
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------- write --
@router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
async def create_subject(
    body: SubjectWrite,
    teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> SubjectOut:
    """Create a subject."""
    subject = Subject(name=body.name, description=body.description, created_by=teacher.id)
    session.add(subject)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A subject with that name already exists."
        ) from e
    await session.refresh(subject)
    return (await _decorate(session, [subject]))[0]


@router.patch("/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: uuid.UUID,
    body: SubjectWrite,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> SubjectOut:
    """Rename a subject or change its description."""
    subject = await _subject_or_404(session, subject_id)
    subject.name = body.name
    subject.description = body.description
    session.add(subject)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A subject with that name already exists."
        ) from e
    return (await _decorate(session, [subject]))[0]


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: uuid.UUID,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Removes the subject with its concepts, documents, and indexed chunks."""
    subject = await _subject_or_404(session, subject_id)
    stored = list(
        (
            await session.execute(
                select(Document.stored_path).where(Document.subject_id == subject_id)
            )
        )
        .scalars()
        .all()
    )
    await session.delete(subject)  # FKs cascade to concepts, documents, chunks
    await session.flush()
    for path in stored:
        delete_upload(path)


@router.post("/{subject_id}/concepts", response_model=ConceptOut, status_code=201)
async def create_concept(
    subject_id: uuid.UUID,
    body: ConceptWrite,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> Concept:
    """Add a concept to a subject."""
    await _subject_or_404(session, subject_id)
    concept = Concept(
        subject_id=subject_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        difficulty_level=body.difficulty_level,
    )
    session.add(concept)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That slug is already in use.") from e
    await session.refresh(concept)
    return concept


# ----------------------------------------------------------- documents --
async def _ingest_document(document_id: uuid.UUID) -> None:
    """Chunk, embed, and index one uploaded file.

    Runs as a background task with its own session: the request that scheduled
    it has already returned and its session is closed. Every failure is recorded
    on the document row so the teacher sees *why* in the UI instead of a file
    that silently never becomes searchable.
    """
    from pathlib import Path

    from rag.ingestion import ingest_paths

    # Everything below is inside one try/except, including the very first DB
    # round-trip: this task runs detached from the request that scheduled it,
    # so a failure here has no other way to surface. Without this, any error
    # before the "processing" transition (a dropped DB connection, a pool
    # timeout, the process being recycled mid-task) leaves the document stuck
    # at "pending" forever with no indication of why.
    try:
        async with async_session() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                return
            doc.status = "processing"
            await session.commit()
            subject_id, stored_path = doc.subject_id, doc.stored_path

        n_chunks = await ingest_paths(
            [Path(stored_path)], subject_id=subject_id, document_id=document_id
        )

        async with async_session() as session:
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = "ready" if n_chunks else "failed"
                doc.n_chunks = n_chunks
                doc.ingested_at = datetime.now(UTC)
                if not n_chunks:
                    doc.error_message = "No readable text was found in this file."
                await session.commit()
        log.info("Ingested document %s into %d chunks", document_id, n_chunks)
    except Exception as e:  # the reason must reach the teacher, whatever it is
        log.exception("Ingestion failed for document %s", document_id)
        try:
            async with async_session() as session:
                doc = await session.get(Document, document_id)
                if doc is not None:
                    doc.status = "failed"
                    doc.error_message = str(e)[:500]
                    await session.commit()
        except Exception:  # pragma: no cover - last resort, must not raise further
            log.exception("Could not record ingestion failure for %s", document_id)


@router.get("/{subject_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    subject_id: uuid.UUID,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> list[Document]:
    """Uploaded files and their ingestion status. Poll this after an upload."""
    await _subject_or_404(session, subject_id)
    stmt = (
        select(Document)
        .where(Document.subject_id == subject_id)
        .order_by(Document.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "/{subject_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    subject_id: uuid.UUID,
    background: BackgroundTasks,
    file: UploadFile,
    teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> Document:
    """Accept a PDF, Markdown, or text file and index it for this subject."""
    await _subject_or_404(session, subject_id)
    validate_suffix(file.filename)
    stored = await save_upload(file)

    doc = Document(
        subject_id=subject_id,
        filename=file.filename or stored.name,
        stored_path=str(stored),
        size_bytes=stored.stat().st_size,
        status="pending",
        uploaded_by=teacher.id,
    )
    session.add(doc)
    await session.flush()
    await session.refresh(doc)

    background.add_task(_ingest_document, doc.id)
    return doc


@documents_router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Remove a document, its indexed chunks, and the stored file."""
    from rag.stores.pgvector_store import delete_by_document

    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such document.")
    stored_path = doc.stored_path
    await delete_by_document(document_id)
    await session.delete(doc)
    await session.flush()
    delete_upload(stored_path)
