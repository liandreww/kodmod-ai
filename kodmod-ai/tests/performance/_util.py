"""Shared helpers for the Stage 8 HTTP / WS load probes."""

from __future__ import annotations

import asyncio
import itertools
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class LatencyReport:
    """Summary of a batch of timed async calls (seconds)."""

    samples: list[float] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    errors: int = 0

    @property
    def n(self) -> int:
        return len(self.samples) + self.errors

    @property
    def error_rate(self) -> float:
        return self.errors / self.n if self.n else 0.0

    def pct(self, q: float) -> float:
        if not self.samples:
            return float("inf")
        ordered = sorted(self.samples)
        k = min(len(ordered) - 1, round(q * (len(ordered) - 1)))
        return ordered[k]

    @property
    def p50(self) -> float:
        return self.pct(0.50)

    @property
    def p95(self) -> float:
        return self.pct(0.95)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else float("inf")

    def status_counts(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for s in self.statuses:
            out[s] = out.get(s, 0) + 1
        return out

    def as_metrics(self, prefix: str = "") -> dict:
        p = f"{prefix}_" if prefix else ""
        return {
            f"{p}n": self.n,
            f"{p}p50_ms": round(self.p50 * 1000, 1),
            f"{p}p95_ms": round(self.p95 * 1000, 1),
            f"{p}mean_ms": round(self.mean * 1000, 1),
            f"{p}error_rate": round(self.error_rate, 4),
            f"{p}status_counts": self.status_counts(),
        }


async def run_load(
    call: Callable[[], Awaitable[int]],
    *,
    concurrency: int,
    rounds: int,
) -> LatencyReport:
    """Fire ``concurrency`` copies of ``call`` per round, ``rounds`` rounds.

    ``call`` must perform one request and return its HTTP status code (or raise).
    """
    report = LatencyReport()

    async def _one() -> None:
        start = time.perf_counter()
        try:
            status = await call()
        except Exception:
            report.errors += 1
            return
        dt = time.perf_counter() - start
        report.samples.append(dt)
        report.statuses.append(status)

    for _ in range(rounds):
        await asyncio.gather(*(_one() for _ in range(concurrency)))
    return report


async def soak(
    call: Callable[[], Awaitable[int]],
    *,
    seconds: int,
    concurrency: int,
    snapshot: Callable[[], Awaitable[dict]] | None = None,
    snapshot_every: float = 5.0,
) -> tuple[LatencyReport, list[dict]]:
    """Hold ``concurrency`` in flight for ``seconds``; sample ``snapshot`` periodically."""
    report = LatencyReport()
    snaps: list[dict] = []
    deadline = time.perf_counter() + seconds
    next_snap = 0.0

    async def _one() -> None:
        start = time.perf_counter()
        try:
            status = await call()
        except Exception:
            report.errors += 1
            return
        report.samples.append(time.perf_counter() - start)
        report.statuses.append(status)

    while time.perf_counter() < deadline:
        await asyncio.gather(*(_one() for _ in range(concurrency)))
        now = time.perf_counter()
        if snapshot is not None and now >= next_snap:
            snap = await snapshot()
            snap["t"] = round(seconds - (deadline - now), 1)
            snaps.append(snap)
            next_snap = now + snapshot_every
    return report, snaps


def is_flat(values: list[float], *, tolerance: float = 0.5) -> bool:
    """True if max is within ``tolerance`` (fractional) of min — i.e. no runaway growth."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return True
    lo = min(vals)
    hi = max(vals)
    if lo <= 0:
        return hi <= tolerance or hi == 0
    return (hi - lo) / lo <= tolerance


def is_monotonic_growth(values: list[float], *, min_rise: float = 0.05) -> bool:
    """True only if the series climbs, sample after sample, by a *meaningful* amount.

    A real leak keeps growing across the whole window. A healthy process instead
    takes a small one-time step up (lazy imports / JIT / pool fill / RSS
    quantisation) over the first sample or two, then plateaus — that must NOT
    count. So we require both:

    * non-decreasing throughout, and
    * total rise from first to last sample >= ``min_rise`` (fraction of the
      first sample). A 0.1 MB creep on a 250 MB process (0.04%) is noise; a leak
      over even a short probe blows well past 5%.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return False
    non_decreasing = all(b >= a for a, b in itertools.pairwise(vals))
    base = vals[0] if vals[0] > 0 else 1.0
    return non_decreasing and (vals[-1] - vals[0]) / base >= min_rise
