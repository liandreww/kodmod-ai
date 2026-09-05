"""
KODMOD AI — SQLAlchemy ORM Models
=================================

**This module is the single source of truth for the database schema.** There is
no hand-maintained `schema.sql`; Alembic migrations under
`database/migrations/versions/` are generated from these models and are what
every environment deploys.

Identity model
--------------
One `users` table carries every account, distinguished by `role`
(`student` | `teacher` | `admin`). There is no separate students or teachers
table. Learner-specific columns (`preferred_language`, `accessibility_profile`)
live on the same row and are simply unused for the other two roles.

Foreign keys that point at a learner are still named `student_id` even though
they now reference `users.id`. That is deliberate: it keeps the analytics and
memory layers readable, and `student_id` says what the column *means* in a way
`user_id` would not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config.settings import settings

# Roles and statuses are stored as plain strings guarded by CHECK constraints
# rather than native PG enums: adding a value later is an ordinary migration
# instead of an ALTER TYPE dance.
Role = Literal["student", "teacher", "admin"]
ROLES: tuple[str, ...] = ("student", "teacher", "admin")

DocumentStatus = Literal["pending", "processing", "ready", "failed"]
DOCUMENT_STATUSES: tuple[str, ...] = ("pending", "processing", "ready", "failed")


def _now() -> datetime:
    """Timezone-aware UTC now. `datetime.utcnow` is deprecated and returns naive."""
    return datetime.now(UTC)


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


# ----------------------------------------------------------------- people --
class User(Base):
    """Every account in the system: students, teachers, and admins."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_sql_in("role", ROLES), name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Learner-facing preferences. Unused for teachers and admins.
    grade_level: Mapped[str | None] = mapped_column(String(50))
    preferred_language: Mapped[str] = mapped_column(String(8), default="id")
    accessibility_profile: Mapped[str] = mapped_column(String(50), default="blind")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions = relationship("LearningSession", back_populates="student")
    mastery = relationship("MasteryScore", back_populates="student")

    @property
    def is_student(self) -> bool:
        return self.role == "student"


class InvitationCode(Base):
    """A code someone must present to register. Admins mint these."""

    __tablename__ = "invitation_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def is_redeemable(self, *, at: datetime | None = None) -> bool:
        """True when this code can still be spent."""
        now = at or _now()
        if not self.is_active or self.used_count >= self.max_uses:
            return False
        return not (self.expires_at and self.expires_at <= now)


# --------------------------------------------------------------- content --
class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    prerequisite_ids: Mapped[list] = mapped_column(JSON, default=list)
    difficulty_level: Mapped[str] = mapped_column(String(20), default="medium")


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    audio_friendly_summary: Mapped[str | None] = mapped_column(Text)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10)
    accessibility_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), default="spoken")
    options: Mapped[list] = mapped_column(JSON, default=list)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict | None] = mapped_column(JSON)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    is_audio_friendly: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    """A curriculum file a teacher uploaded, and how its ingestion went."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(_sql_in("status", DOCUMENT_STATUSES), name="ck_documents_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurriculumChunk(Base):
    """An embedded slice of a document, read by `rag/stores/pgvector_store.py`.

    That module uses raw SQL for the vector operators, so this model exists to
    keep the table under Alembic's control and the column list in one place.
    The two must be changed together.
    """

    __tablename__ = "curriculum_chunks"
    __table_args__ = (
        Index(
            "ix_curriculum_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.EMBEDDING_DIM))
    source: Mapped[str] = mapped_column(String(500), default="")
    language: Mapped[str] = mapped_column(String(8), default="id")
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    section_title: Mapped[str | None] = mapped_column(String(300))
    accessibility_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# -------------------------------------------------------------- sessions --
class LearningSession(Base):
    """One conversation.

    Backs the student's history sidebar and the teacher's transcript view;
    `InteractionLog` rows are its turns.
    """

    __tablename__ = "learning_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String(40), default="tutoring")
    summary: Mapped[str | None] = mapped_column(Text)

    student = relationship("User", back_populates="sessions")
    interactions = relationship("InteractionLog", back_populates="session")


class InteractionLog(Base):
    __tablename__ = "interaction_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    role: Mapped[str] = mapped_column(String(20))  # student | assistant | system
    intent: Mapped[str | None] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    session = relationship("LearningSession", back_populates="interactions")


# ------------------------------------------------------------------ quiz --
class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    final_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quiz_sessions.id", ondelete="CASCADE")
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40))
    options: Mapped[list] = mapped_column(JSON, default=list)
    correct_answer: Mapped[str] = mapped_column(Text)
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="SET NULL")
    )
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quiz_sessions.id", ondelete="CASCADE")
    )
    quiz_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="CASCADE")
    )
    student_answer: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    feedback: Mapped[str | None] = mapped_column(Text)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------- mastery --
class MasteryScore(Base):
    __tablename__ = "mastery_scores"
    __table_args__ = (UniqueConstraint("student_id", "concept_id", name="uq_student_concept"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE")
    )
    mastery: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    n_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    student = relationship("User", back_populates="mastery")


class Misconception(Base):
    __tablename__ = "misconceptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


# ----------------------------------------------------------- analytics --
class AnalyticsReport(Base):
    __tablename__ = "analytics_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    report_type: Mapped[str] = mapped_column(String(40), index=True)  # student | weekly | episode:*
    payload: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))  # next_lesson | practice | habit
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    target_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="SET NULL")
    )
    priority: Mapped[int] = mapped_column(Integer, default=1)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
