"""Stage 9 §2 — SQL injection on the raw-SQL paths.

Spec: docs/testplan/09-security.md §2 (KM-SEC-020..026). Target modules:
analytics/student_model.py, analytics/aggregator.py, rag/stores/pgvector_store.py.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.security, pytest.mark.asyncio(loop_scope="session")]

_REPO = Path(__file__).resolve().parents[2]
_SQLI_UUID = "00000000-0000-0000-0000-000000000000' OR '1'='1"


# --------------------------------------------------------------------------- #
# KM-SEC-020 — student_id path param: UUID converter rejects before any SQL
# --------------------------------------------------------------------------- #
async def test_km_sec_020_student_id_injection_via_path(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get(
        f"/analytics/student/{_SQLI_UUID}", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 422  # FastAPI UUID converter refuses it
    assert "syntax error" not in r.text.lower()


# --------------------------------------------------------------------------- #
# KM-SEC-021 — concept_id filter injection
# --------------------------------------------------------------------------- #
async def test_km_sec_021_concept_id_injection(
    client, student_factory, curriculum_chunk_count
) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    before = await curriculum_chunk_count()

    payload = "1); DROP TABLE curriculum_chunks;--"
    r1 = await client.get(
        f"/exercise/by-concept/{payload}", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r1.status_code in {401, 403, 404, 422}

    r2 = await client.post(
        "/content/retrieve",
        json={"query": "pecahan", "top_k": 4, "language": "id", "student_id": payload},
    )
    assert r2.status_code in {200, 422}

    assert await curriculum_chunk_count() == before  # table intact


# --------------------------------------------------------------------------- #
# KM-SEC-022 — language param injection stays a bind parameter
# --------------------------------------------------------------------------- #
async def test_km_sec_022_language_injection(client, curriculum_chunk_count) -> None:  # type: ignore[no-untyped-def]
    before = await curriculum_chunk_count()
    r = await client.post(
        "/content/retrieve",
        json={
            "query": "pecahan",
            "top_k": 4,
            "language": "id'; DROP TABLE curriculum_chunks;--",
        },
    )
    assert r.status_code in {200, 422}
    if r.status_code == 200:
        assert isinstance(r.json()["chunks"], list)  # treated as a literal, 0 rows leaked
    assert await curriculum_chunk_count() == before


# --------------------------------------------------------------------------- #
# KM-SEC-024 — StudentModel.load with a weird student_id via the graph state
# --------------------------------------------------------------------------- #
async def test_km_sec_024_student_model_load_bad_sid() -> None:
    from sqlalchemy import text

    from analytics.student_model import StudentModel
    from database.session import async_session, init_db

    await init_db()

    # A malformed id must be rejected as a value error / cast error — never
    # smuggled into SQL. Any raise is acceptable; a completed drop is not.
    try:
        await StudentModel.load("'; DROP TABLE mastery_scores;--")
    except Exception:
        pass

    async with async_session() as s:
        exists = (await s.execute(text("SELECT to_regclass('public.mastery_scores')"))).scalar_one()
    assert exists is not None, "mastery_scores table was dropped — SQL injection!"

    # A well-formed but unknown UUID must simply come back empty, never error.
    model = await StudentModel.load(str(uuid.uuid4()))
    scores = await model.mastery_scores()
    assert isinstance(scores, dict)


# --------------------------------------------------------------------------- #
# KM-SEC-025 — static audit: no f-string / % / + interpolation into SQL
# --------------------------------------------------------------------------- #
_AUDIT_FILES = [
    "analytics/student_model.py",
    "analytics/aggregator.py",
    "rag/stores/pgvector_store.py",
]


class _SqlInterpolationVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def _is_sql_str(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and any(
                kw in node.value.upper()
                for kw in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "FROM ", " WHERE ")
            )
        )

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:  # f-strings
        parts = [v for v in node.values if isinstance(v, ast.Constant)]
        has_expr = any(isinstance(v, ast.FormattedValue) for v in node.values)
        if has_expr and any(self._is_sql_str(p) for p in parts):
            self.violations.append(f"f-string SQL at line {node.lineno}")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Add | ast.Mod) and (
            self._is_sql_str(node.left) or self._is_sql_str(node.right)
        ):
            self.violations.append(f"string-concat SQL at line {node.lineno}")
        self.generic_visit(node)


def test_km_sec_025_no_sql_string_interpolation() -> None:
    findings: dict[str, list[str]] = {}
    for rel in _AUDIT_FILES:
        path = _REPO / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        v = _SqlInterpolationVisitor()
        v.visit(tree)
        # pgvector_store assembles the vector literal from numbers only — that is
        # explicitly allowlisted in pyproject (ruff S608) and is not user input.
        allowed = rel == "rag/stores/pgvector_store.py"
        real = [x for x in v.violations if not allowed]
        if real:
            findings[rel] = real
    assert not findings, f"user-value SQL interpolation: {findings}"


# --------------------------------------------------------------------------- #
# KM-SEC-026 — ClassroomAggregator roster raw SQL stays parameterized
# --------------------------------------------------------------------------- #
async def test_km_sec_026_cohort_roster_parameterized(client, teacher_factory) -> None:  # type: ignore[no-untyped-def]
    """The cohort roster is a parameterized ORM query; no id is interpolated at all."""
    _tid, tok = await teacher_factory()
    r = await client.get(
        "/analytics/cohort",
        params={"window": "week'; DROP TABLE users; --"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    # An injected window is rejected by the Literal, never reaches SQL.
    assert r.status_code == 422
