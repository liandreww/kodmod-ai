"""Stage 2 helpers — resolve FastAPI routes without running the lifespan.

FastAPI >= 0.128 keeps ``include_router`` lazy: ``app.routes`` contains
``_IncludedRouter`` wrappers rather than the child ``APIRoute`` objects. These
helpers flatten that back into ``(methods, full_path, route)`` triples so the
contract tests can introspect prefixes, auth dependencies and summaries without
a TestClient / lifespan.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Mount, Route, WebSocketRoute


def _flatten(routes, prefix: str = "") -> Iterator[tuple[frozenset[str], str, object]]:
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            ctx = r.include_context
            child_prefix = prefix + (getattr(ctx, "prefix", "") or "")
            yield from _flatten(ctx.included_router.routes, child_prefix)
        elif isinstance(r, APIRoute | Route):
            yield frozenset(r.methods or []), prefix + r.path, r
        elif isinstance(r, APIWebSocketRoute | WebSocketRoute):
            yield frozenset(["WEBSOCKET"]), prefix + r.path, r
        elif isinstance(r, Mount):
            yield frozenset(["MOUNT"]), prefix + r.path, r


def iter_routes(app) -> list[tuple[frozenset[str], str, object]]:  # type: ignore[no-untyped-def]
    return list(_flatten(app.routes))


def route_dependency_names(route: object) -> set[str]:
    """Names of every dependency callable attached to an APIRoute."""
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    stack = [dependant] if dependant else []
    while stack:
        d = stack.pop()
        call = getattr(d, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", repr(call)))
        stack.extend(getattr(d, "dependencies", []) or [])
    return names


@pytest.fixture
def resolved_routes(fastapi_app):  # type: ignore[no-untyped-def]
    return iter_routes(fastapi_app)


@pytest.fixture
def route_deps():  # type: ignore[no-untyped-def]
    return route_dependency_names
