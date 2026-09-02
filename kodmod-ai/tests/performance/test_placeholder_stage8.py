"""Stage 8 Performance/Load — spec: docs/testplan/08-performance.md

Placeholder skips so `pytest --collect-only` validates layout. Implement per spec.
"""

import pytest

SPEC_IDS = [
    "KM-PERF-001",
    "KM-PERF-002",
    "KM-PERF-003",
    "KM-PERF-004",
    "KM-PERF-005",
    "KM-PERF-010",
    "KM-PERF-011",
    "KM-PERF-012",
    "KM-PERF-013",
    "KM-PERF-020",
    "KM-PERF-021",
    "KM-PERF-030",
    "KM-PERF-031",
    "KM-PERF-040",
    "KM-PERF-041",
    "KM-PERF-042",
    "KM-PERF-043",
    "KM-PERF-044",
    "KM-PERF-045",
]


@pytest.mark.perf
@pytest.mark.parametrize("spec_id", SPEC_IDS)
@pytest.mark.skip(reason="spec placeholder — implement per docs/testplan/08-performance.md")
def test_spec(spec_id: str) -> None:
    raise AssertionError(spec_id)
