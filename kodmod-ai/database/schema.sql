-- =====================================================================
-- KODMOD AI — PostgreSQL Schema
-- =====================================================================
-- Requires:
--   * PostgreSQL 16+
--   * pgvector >= 0.7
--   * pgcrypto (for gen_random_uuid)
--
-- Layout
-- ------
--   1. Identity & profiles      (students, teachers, classrooms, enrollment)
--   2. Curriculum & content     (subjects, concepts, lessons, exercises)
--   3. RAG store                (curriculum_chunks with vector index)
--   4. Sessions & interactions  (learning_sessions, interaction_logs)
--   5. Quiz                     (quiz_sessions, quiz_questions, quiz_attempts)
--   6. Student model            (mastery_scores, misconceptions)
--   7. Analytics                (analytics_reports, recommendations)
--   8. LangGraph checkpoints    (handled by AsyncPostgresSaver — separate schema)
--   9. Audit & accessibility    (audit_log, accessibility_prefs)
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------
-- 1. Identity & profiles
-- ---------------------------------------------------------------------

CREATE TABLE students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id VARCHAR(64) UNIQUE,
    display_name VARCHAR(120) NOT NULL,
    date_of_birth DATE,
    grade_level INT,
    language CHAR(2) NOT NULL DEFAULT 'id',
    visual_status VARCHAR(20) NOT NULL DEFAULT 'low_vision'
        CHECK (visual_status IN ('blind', 'low_vision', 'partially_sighted', 'sighted')),
    accessibility_prefs JSONB NOT NULL DEFAULT '{}'::jsonb,
    learning_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_students_external ON students(external_id);

CREATE TABLE teachers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    school_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE classrooms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL,
    teacher_id UUID NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE classroom_enrollment (
    classroom_id UUID NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (classroom_id, student_id)
);


-- ---------------------------------------------------------------------
-- 2. Curriculum & content
-- ---------------------------------------------------------------------

CREATE TABLE subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(32) UNIQUE NOT NULL,            -- e.g. 'MATH-7'
    name VARCHAR(120) NOT NULL,
    grade_level INT
);

CREATE TABLE concepts (
    id VARCHAR(64) PRIMARY KEY,                  -- human-readable, e.g. 'algebra.linear.solving'
    subject_id UUID NOT NULL REFERENCES subjects(id),
    title VARCHAR(200) NOT NULL,
    description TEXT,
    difficulty VARCHAR(12) NOT NULL DEFAULT 'medium',
    prerequisites VARCHAR(64)[] NOT NULL DEFAULT '{}',
    audio_friendly BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_concepts_subject ON concepts(subject_id);
CREATE INDEX idx_concepts_prereqs ON concepts USING GIN (prerequisites);

CREATE TABLE lessons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id VARCHAR(64) NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,                          -- markdown / plain
    audio_uri TEXT,                              -- pre-rendered narration
    estimated_minutes INT,
    accessibility_score NUMERIC(3,2),            -- 0–1
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exercises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id VARCHAR(64) NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL,                   -- mcq | spoken | explain | reasoning | step_by_step
    difficulty VARCHAR(12) NOT NULL,
    body JSONB NOT NULL,                         -- question + options + rubric
    is_audio_friendly BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_exercises_concept ON exercises(concept_id);


-- ---------------------------------------------------------------------
-- 3. RAG store
-- ---------------------------------------------------------------------

CREATE TABLE curriculum_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,                     -- lesson_id or document_id
    source_type VARCHAR(32) NOT NULL,            -- 'lesson' | 'document' | 'transcript'
    concept_ids VARCHAR(64)[] NOT NULL DEFAULT '{}',
    text TEXT NOT NULL,
    embedding vector(1024) NOT NULL,             -- BGE-M3
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for fast cosine ANN
CREATE INDEX idx_chunks_embedding_hnsw
    ON curriculum_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunks_concepts ON curriculum_chunks USING GIN (concept_ids);
CREATE INDEX idx_chunks_text_trgm ON curriculum_chunks USING GIN (text gin_trgm_ops);


-- ---------------------------------------------------------------------
-- 4. Sessions & interactions
-- ---------------------------------------------------------------------

CREATE TABLE learning_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    total_turns INT NOT NULL DEFAULT 0,
    primary_intent VARCHAR(32),
    summary TEXT
);
CREATE INDEX idx_sessions_student_started ON learning_sessions(student_id, started_at DESC);

CREATE TABLE interaction_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE CASCADE,
    turn_index INT NOT NULL,
    student_input TEXT,
    intent VARCHAR(32),
    intent_confidence NUMERIC(3,2),
    agent_response TEXT,
    last_node VARCHAR(64),
    latency_ms INT,
    token_in INT,
    token_out INT,
    audio_input_uri TEXT,
    audio_output_uri TEXT,
    emotional_state VARCHAR(20),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_state JSONB
);
CREATE INDEX idx_logs_session ON interaction_logs(session_id, turn_index);
CREATE INDEX idx_logs_occurred ON interaction_logs(occurred_at DESC);


-- ---------------------------------------------------------------------
-- 5. Quiz
-- ---------------------------------------------------------------------

CREATE TABLE quiz_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    concept_id VARCHAR(64) REFERENCES concepts(id),
    difficulty VARCHAR(12),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    cumulative_score NUMERIC(4,3),
    misconceptions TEXT[] NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_quizsess_student ON quiz_sessions(student_id, started_at DESC);

CREATE TABLE quiz_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_session_id UUID NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    type VARCHAR(20) NOT NULL,
    concept_id VARCHAR(64) REFERENCES concepts(id),
    text TEXT NOT NULL,
    options JSONB,
    expected_answer TEXT,
    rubric JSONB,
    difficulty VARCHAR(12)
);

CREATE TABLE quiz_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    student_answer TEXT,
    score NUMERIC(4,3) NOT NULL,
    is_correct BOOLEAN NOT NULL,
    confidence NUMERIC(3,2),
    response_latency_ms INT,
    feedback TEXT,
    answered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_attempts_student ON quiz_attempts(student_id, answered_at DESC);


-- ---------------------------------------------------------------------
-- 6. Student model — mastery & misconceptions
-- ---------------------------------------------------------------------

CREATE TABLE mastery_scores (
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    concept_id VARCHAR(64) NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    score NUMERIC(4,3) NOT NULL,                 -- 0–1
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.5,
    n_attempts INT NOT NULL DEFAULT 0,
    last_practiced TIMESTAMPTZ,
    velocity NUMERIC(5,3),                       -- mastery delta / day
    PRIMARY KEY (student_id, concept_id)
);
CREATE INDEX idx_mastery_student_score ON mastery_scores(student_id, score);

CREATE TABLE misconceptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    concept_id VARCHAR(64) REFERENCES concepts(id),
    label VARCHAR(200) NOT NULL,
    evidence TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);


-- ---------------------------------------------------------------------
-- 7. Analytics
-- ---------------------------------------------------------------------

CREATE TABLE analytics_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    overall_mastery NUMERIC(4,3),
    avg_quiz_score NUMERIC(4,3),
    sessions_total INT,
    streak_days INT,
    engagement_index NUMERIC(4,3),
    weak_concepts VARCHAR(64)[] DEFAULT '{}',
    strong_concepts VARCHAR(64)[] DEFAULT '{}',
    spoken_summary TEXT,
    teacher_summary TEXT,
    raw JSONB,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_reports_student_period ON analytics_reports(student_id, period_end DESC);

CREATE TABLE recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL,                   -- next_lesson | practice | habit
    text TEXT NOT NULL,
    concept_id VARCHAR(64),
    is_acted_on BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------
-- 9. Audit
-- ---------------------------------------------------------------------

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_type VARCHAR(20) NOT NULL,             -- 'student' | 'teacher' | 'system'
    actor_id UUID,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(32),
    resource_id VARCHAR(64),
    payload JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_actor ON audit_log(actor_id, occurred_at DESC);


-- ---------------------------------------------------------------------
-- Helpful views for the teacher dashboard
-- ---------------------------------------------------------------------

CREATE OR REPLACE VIEW v_classroom_mastery AS
SELECT
    e.classroom_id,
    m.concept_id,
    AVG(m.score)::numeric(4,3) AS avg_mastery,
    COUNT(*)                   AS n_students
FROM classroom_enrollment e
JOIN mastery_scores m ON m.student_id = e.student_id
GROUP BY e.classroom_id, m.concept_id;

CREATE OR REPLACE VIEW v_recent_engagement AS
SELECT
    s.student_id,
    DATE_TRUNC('day', s.started_at) AS day,
    COUNT(*) AS sessions,
    SUM(s.total_turns) AS turns
FROM learning_sessions s
WHERE s.started_at >= now() - INTERVAL '30 days'
GROUP BY s.student_id, DATE_TRUNC('day', s.started_at);
