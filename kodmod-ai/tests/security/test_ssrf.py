"""Stage 9 §3 — SSRF / untrusted fetch on the audio-input path.

Spec: docs/testplan/09-security.md §3 (KM-SEC-030..034). Oracle:
``voice/stt.py::_ensure_local`` and ``voice/streaming.py::fetch_audio`` — the two
places an ``audio_input_path`` / upload URL is turned into bytes.

These run in-process (no api needed): the SSRF surface is not reachable over an
HTTP route today, so we exercise the helpers directly and assert the TARGET
(reject link-local / localhost / private / non-file schemes / traversal). A
proper guard must refuse *before* any socket is opened — so the check is
"raises a guard error (ValueError/PermissionError) quickly", not "raises
anything" (a connection error or timeout means there is no guard).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = [pytest.mark.security]

_SSRF_URLS = [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://metadata.google.internal/computeMetadata/v1/",
]
_LOCALHOST_URLS = [
    "http://localhost:8000/metrics",
    "http://127.0.0.1:8000/ready",
]
_PRIVATE_URLS = [
    "http://10.0.0.5/x",
    "http://192.168.1.1/x",
    "http://db.internal/x",
]


async def _assert_guarded(url: str) -> None:
    """fetch_audio(url) must raise a *guard* error fast, not attempt the request."""
    from voice.streaming import fetch_audio

    try:
        raw = await asyncio.wait_for(fetch_audio(url), timeout=4.0)
    except (ValueError, PermissionError):
        return  # explicit SSRF guard fired — target behaviour
    except Exception as exc:
        raise AssertionError(
            f"no SSRF guard for {url!r}: fetch was attempted ({type(exc).__name__}: {exc})"
        ) from exc
    raise AssertionError(f"no SSRF guard for {url!r}: fetch returned {len(raw)} bytes")


def _ensure_local():
    from voice.stt import _ensure_local as fn

    return fn


# --------------------------------------------------------------------------- #
# KM-SEC-030 — cloud metadata endpoints
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "SSRF guard — voice/streaming.py::fetch_audio GETs any http(s) URL with no allowlist / "
    "IP-range check; target: reject link-local metadata hosts before connecting"
)
@pytest.mark.parametrize("url", _SSRF_URLS)
async def test_km_sec_030_ssrf_metadata_rejected(url) -> None:  # type: ignore[no-untyped-def]
    await _assert_guarded(url)


# --------------------------------------------------------------------------- #
# KM-SEC-031 — localhost / loopback
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "SSRF guard — fetch_audio does not block loopback; target: reject localhost / 127.0.0.0/8"
)
@pytest.mark.parametrize("url", _LOCALHOST_URLS)
async def test_km_sec_031_ssrf_localhost_rejected(url) -> None:  # type: ignore[no-untyped-def]
    await _assert_guarded(url)


# --------------------------------------------------------------------------- #
# KM-SEC-032 — private RFC1918 / *.internal
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "SSRF guard — fetch_audio does not resolve+range-check the host; target: reject RFC1918 "
    "and non-public DNS names"
)
@pytest.mark.parametrize("url", _PRIVATE_URLS)
async def test_km_sec_032_ssrf_private_rejected(url) -> None:  # type: ignore[no-untyped-def]
    await _assert_guarded(url)


# --------------------------------------------------------------------------- #
# KM-SEC-033 — local path traversal
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "path traversal — voice/stt.py::_ensure_local returns any non-URL string unchanged; "
    "target: reject '..' or normalise the path under UPLOAD_DIR"
)
def test_km_sec_033_path_traversal_rejected() -> None:
    from pathlib import Path

    from config.settings import settings

    ensure = _ensure_local()
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    for bad in ("../../etc/passwd", "..\\..\\windows\\win.ini", "/etc/shadow"):
        try:
            resolved = ensure(bad)
        except (ValueError, PermissionError):
            continue  # rejected outright — acceptable
        assert Path(resolved).resolve().is_relative_to(upload_root), (
            f"{bad!r} resolved to {resolved!r} outside {upload_root}"
        )


# --------------------------------------------------------------------------- #
# KM-SEC-034 — disallowed URL schemes
# --------------------------------------------------------------------------- #
def test_km_sec_034_http_s3_schemes_rejected() -> None:
    """Already refused by _ensure_local (NotImplementedError) — regression guard."""
    ensure = _ensure_local()
    for uri in ("http://x/y", "https://x/y", "s3://bucket/key", "minio://b/k"):
        with pytest.raises((NotImplementedError, ValueError, PermissionError)):
            ensure(uri)


@pytest.mark.known_bug(
    "scheme allowlist — _ensure_local passes file:// and gopher:// straight through; target: "
    "only bare local filesystem paths are accepted"
)
def test_km_sec_034b_file_gopher_schemes_rejected() -> None:
    ensure = _ensure_local()
    for uri in ("file:///etc/passwd", "gopher://evil/x", "ftp://evil/x"):
        with pytest.raises((NotImplementedError, ValueError, PermissionError)):
            ensure(uri)
