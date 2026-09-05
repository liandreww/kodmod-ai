"""
KODMOD AI — Upload Handling
===========================

Persists teacher-uploaded curriculum documents to `settings.UPLOAD_DIR` before
the RAG ingestion job picks them up.

Two things this module is responsible for and callers must not re-implement:

* **Extension allowlist.** Only the formats `rag.ingestion` can actually read
  (`.pdf`, `.md`, `.txt`) are accepted.
* **Name safety.** The stored filename is always a fresh UUID plus the
  validated suffix, so a hostile ``filename`` can never escape UPLOAD_DIR or
  overwrite an existing document.

The size cap is enforced *while streaming*, not after: a request that exceeds
`MAX_UPLOAD_MB` is rejected and its partial file removed, so an oversized
upload can never fill the disk.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, status

from config.settings import settings

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = frozenset({".pdf", ".md", ".txt"})

_CHUNK = 1 << 20  # 1 MiB


def validate_suffix(filename: str | None) -> str:
    """Return the lowercased suffix of `filename`, or raise 415."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{suffix or filename}'. Allowed: {allowed}",
        )
    return suffix


async def save_upload(upload_file, dest_dir: Path | None = None) -> Path:
    """
    Stream a Starlette/FastAPI UploadFile to disk and return the stored path.

    Raises
    ------
    HTTPException
        415 if the extension is not allowed, 413 if the body exceeds
        `settings.MAX_UPLOAD_MB`.
    """
    suffix = validate_suffix(getattr(upload_file, "filename", None))

    dest = dest_dir or settings.UPLOAD_DIR
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"{uuid.uuid4().hex}{suffix}"

    limit = settings.MAX_UPLOAD_BYTES
    total = 0
    try:
        with open(out_path, "wb") as f:
            while True:
                chunk = await upload_file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File is larger than {settings.MAX_UPLOAD_MB} MB.",
                    )
                f.write(chunk)
    except BaseException:
        out_path.unlink(missing_ok=True)
        raise

    if total == 0:
        out_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty.",
        )

    logger.info("Saved upload to %s (%d bytes)", out_path, total)
    return out_path


def delete_upload(stored_path: str | Path) -> None:
    """Remove a stored upload, tolerating a file that is already gone."""
    try:
        Path(stored_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete upload %s", stored_path, exc_info=True)
