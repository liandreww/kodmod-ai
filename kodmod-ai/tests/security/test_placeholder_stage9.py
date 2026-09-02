"""Stage 9 Security — spec: docs/testplan/09-security.md

Placeholder skips so `pytest --collect-only` validates layout. Implement per spec.
"""

import pytest

SPEC_IDS = [
    "KM-SEC-001",
    "KM-SEC-002",
    "KM-SEC-003",
    "KM-SEC-004",
    "KM-SEC-005",
    "KM-SEC-006",
    "KM-SEC-007",
    "KM-SEC-008",
    "KM-SEC-010",
    "KM-SEC-011",
    "KM-SEC-013",
    "KM-SEC-014",
    "KM-SEC-020",
    "KM-SEC-021",
    "KM-SEC-022",
    "KM-SEC-025",
    "KM-SEC-030",
    "KM-SEC-031",
    "KM-SEC-032",
    "KM-SEC-033",
    "KM-SEC-040",
    "KM-SEC-041",
    "KM-SEC-042",
    "KM-SEC-043",
    "KM-SEC-046",
    "KM-SEC-050",
    "KM-SEC-060",
    "KM-SEC-062",
    "KM-SEC-063",
    "KM-SEC-070",
    "KM-SEC-071",
    "KM-SEC-072",
]


@pytest.mark.security
@pytest.mark.parametrize("spec_id", SPEC_IDS)
@pytest.mark.skip(reason="spec placeholder — implement per docs/testplan/09-security.md")
def test_spec(spec_id: str) -> None:
    raise AssertionError(spec_id)
