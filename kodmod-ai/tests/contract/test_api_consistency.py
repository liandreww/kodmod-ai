"""Stage 2 — Contract: handler <-> response_model consistency, OpenAPI, route inventory.

Spec: docs/testplan/02-contract.md §2 (KM-CONTRACT-020..028).

Static introspection only: imports ``api.main:app`` for ``app.openapi()`` /
``app.routes`` and AST-parses route modules. The lifespan never runs (no DB /
checkpointer needed).
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_ROUTES_DIR = Path(__file__).resolve().parents[2] / "api" / "routes"


def _func_ast(module_path: Path, func_name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            return node
    raise AssertionError(f"{func_name} not found in {module_path.name}")


def _response_call_kwargs(func: ast.AST, ctor_name: str) -> set[str]:
    """Keyword names passed to ``ctor_name(...)`` anywhere inside ``func``."""
    kws: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = node.func
            name = getattr(callee, "id", None) or getattr(callee, "attr", None)
            if name == ctor_name:
                kws.update(k.arg for k in node.keywords if k.arg)
    return kws


def _body_attr_reads(func: ast.AST, param: str = "body") -> set[str]:
    """Attribute names read off ``param`` (e.g. ``body.session_id``)."""
    attrs: set[str] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == param
        ):
            attrs.add(node.attr)
    return attrs


# --------------------------------------------------------------------------- #
# KM-CONTRACT-020 — quiz handlers only pass fields the response model declares
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#5 — api/routes/quiz.py builds QuizStartResponse/QuizSubmitResponse with kwargs "
    "(session_id, question_audio_uri, feedback_text, feedback_audio_uri, is_session_complete) "
    "that models/quiz.py does not declare"
)
def test_km_contract_020_quiz_handler_response_kwargs_match_model() -> None:
    from models.quiz import QuizStartResponse, QuizSubmitResponse

    quiz_py = _ROUTES_DIR / "quiz.py"
    start = _func_ast(quiz_py, "start_quiz")
    submit = _func_ast(quiz_py, "submit_answer")

    start_kwargs = _response_call_kwargs(start, "QuizStartResponse")
    submit_kwargs = _response_call_kwargs(submit, "QuizSubmitResponse")
    assert start_kwargs, "no QuizStartResponse(...) call found"
    assert submit_kwargs, "no QuizSubmitResponse(...) call found"

    assert start_kwargs <= set(QuizStartResponse.model_fields), (
        f"unknown kwargs: {start_kwargs - set(QuizStartResponse.model_fields)}"
    )
    assert submit_kwargs <= set(QuizSubmitResponse.model_fields), (
        f"unknown kwargs: {submit_kwargs - set(QuizSubmitResponse.model_fields)}"
    )


# --------------------------------------------------------------------------- #
# KM-CONTRACT-021 — quiz submit handler reads request fields the model declares
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#5 — submit_answer reads body.session_id / body.answer_text; QuizSubmitRequest "
    "declares quiz_session_id / student_answer"
)
def test_km_contract_021_quiz_submit_reads_declared_request_fields() -> None:
    from models.quiz import QuizSubmitRequest

    submit = _func_ast(_ROUTES_DIR / "quiz.py", "submit_answer")
    reads = _body_attr_reads(submit, "body")
    assert reads, "handler reads nothing off body?"
    assert reads <= set(QuizSubmitRequest.model_fields), (
        f"handler reads undeclared request fields: {reads - set(QuizSubmitRequest.model_fields)}"
    )


# --------------------------------------------------------------------------- #
# KM-CONTRACT-022 — _load_mastery does not chain two coroutines  (#6, FIXED)
# --------------------------------------------------------------------------- #
def test_km_contract_022_load_mastery_not_chained_coroutine() -> None:
    from api.routes.quiz import _load_mastery

    src = inspect.getsource(_load_mastery)
    assert ".load(" in src and ".mastery_scores()" in src
    # the bug form was `StudentModel.load(id).mastery_scores()` on one expression
    assert "load(student_id).mastery_scores()" not in src.replace(" ", "")
    assert src.count("await ") >= 2, "expected two separate awaits (load, then mastery_scores)"


# --------------------------------------------------------------------------- #
# KM-CONTRACT-023 — /openapi.json generates
# --------------------------------------------------------------------------- #
def test_km_contract_023_openapi_schema_valid(fastapi_app) -> None:  # type: ignore[no-untyped-def]
    schema = fastapi_app.openapi()
    assert isinstance(schema, dict)
    assert schema.get("openapi", "").startswith("3.")
    assert schema.get("paths")


# --------------------------------------------------------------------------- #
# KM-CONTRACT-024 — every operation carries a summary or description
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "docs — several route handlers (health.live/ready/version, student.get_me, ...) have "
    "neither a summary nor a docstring-derived description in the OpenAPI schema"
)
def test_km_contract_024_every_route_documented(resolved_routes) -> None:  # type: ignore[no-untyped-def]
    from fastapi.routing import APIRoute

    undocumented = []
    for methods, path, r in resolved_routes:
        if not isinstance(r, APIRoute) or "MOUNT" in methods:
            continue
        if not (r.summary or "").strip() and not (r.description or "").strip():
            undocumented.append(f"{sorted(methods)} {path}")
    assert not undocumented, f"undocumented operations: {undocumented}"


# --------------------------------------------------------------------------- #
# KM-CONTRACT-025 — health router mounts at /live,/ready,/version (no /health)
# --------------------------------------------------------------------------- #
def test_km_contract_025_health_paths_have_no_prefix(resolved_routes) -> None:  # type: ignore[no-untyped-def]
    paths = {path for _m, path, _r in resolved_routes}
    assert {"/live", "/ready", "/version"} <= paths
    assert not any(p.startswith("/health/") for p in paths), (
        "health router unexpectedly mounted under /health"
    )


# --------------------------------------------------------------------------- #
# KM-CONTRACT-026 — router prefixes
# --------------------------------------------------------------------------- #
def test_km_contract_026_router_prefixes(resolved_routes) -> None:  # type: ignore[no-untyped-def]
    paths = {path for _m, path, _r in resolved_routes}
    for prefix in (
        "/auth/",
        "/chat/",
        "/quiz/",
        "/teacher/",
        "/admin/",
        "/subjects",
        "/documents/",
        "/analytics/",
        "/exercise/",
        "/content/",
        "/ws/",
    ):
        assert any(p.startswith(prefix) for p in paths), f"no route under {prefix}"
    assert "/student" in paths or any(p.startswith("/student/") for p in paths)


# --------------------------------------------------------------------------- #
# KM-CONTRACT-027 — /metrics mounted without an auth dependency  (#14, noted)
# --------------------------------------------------------------------------- #
def test_km_contract_027_metrics_mounted_unauthenticated(resolved_routes, route_deps) -> None:  # type: ignore[no-untyped-def]
    metrics = [(m, p, r) for m, p, r in resolved_routes if p == "/metrics"]
    assert metrics, "/metrics is not mounted"
    _m, _p, route = metrics[0]
    # documented finding #14: no auth wrapper — Stage 4/9 decides the fix.
    deps = route_deps(route)
    assert "current_student" not in deps and "current_teacher" not in deps


# --------------------------------------------------------------------------- #
# KM-CONTRACT-028 — api/routes/exercise imports clean; the symbol it calls is missing
# --------------------------------------------------------------------------- #
def test_km_contract_028a_exercise_module_imports() -> None:
    mod = importlib.import_module("api.routes.exercise")
    assert hasattr(mod, "router")


@pytest.mark.known_bug(
    "#7 — api/routes/exercise.generate_exercises calls "
    "agents.problem_generator.generate_questions_for_student, which does not exist"
)
def test_km_contract_028b_exercise_generator_symbol_exists() -> None:
    pg = importlib.import_module("agents.problem_generator")
    assert hasattr(pg, "generate_questions_for_student")
