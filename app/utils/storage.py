# app/utils/storage.py
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import AsyncIterator, Iterable, Iterator, Tuple

from fastapi import HTTPException, UploadFile, status


class LocalStorage:
    """
    Simple local disk storage under a base directory with optional subdir.
    - Prevents path traversal
    - Validates PDFs by header
    - Enforces max size (MB)
    """

    def __init__(self, *, base_dir: Path | str, subdir: str = "", max_mb: int = 20):
        self.base_dir = Path(base_dir).resolve()
        self.subdir = subdir.strip("/\\")
        self.root = (self.base_dir / self.subdir).resolve() if self.subdir else self.base_dir
        self.max_bytes = int(max_mb) * 1024 * 1024
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------
    # internal helpers
    # ---------------------------
    def _safe_path(self, rel_path: str) -> Path:
        """Join safely under root and forbid .. traversal."""
        rel = Path(rel_path)
        if rel.is_absolute() or any(part in ("..",) for part in rel.parts):
            raise HTTPException(status_code=400, detail="Invalid relative path")
        full = (self.root / rel).resolve()
        if self.root not in full.parents and full != self.root:
            raise HTTPException(status_code=400, detail="Path escapes storage root")
        return full

    def _slugify(self, name: str) -> str:
        base = re.sub(r"[^\w\-.]+", "_", name).strip("._")
        return base or "file"

    # ---------------------------
    # public API
    # ---------------------------
    async def save_pdf(self, file: UploadFile) -> dict:
        """Save a PDF UploadFile -> returns metadata dict."""
        data = await file.read()
        size = len(data)

        if size == 0:
            raise HTTPException(status_code=400, detail="Empty file")

        if size > self.max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (>{self.max_bytes // (1024*1024)} MB)",
            )

        # quick magic header check
        if not data.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="Not a valid PDF (missing %PDF header)")

        # filename
        orig = file.filename or "upload.pdf"
        stem = self._slugify(Path(orig).stem)
        ext = ".pdf"
        fname = f"{stem}-{uuid.uuid4().hex[:8]}{ext}"

        path = self._safe_path(fname)
        path.write_bytes(data)

        rel_path = path.relative_to(self.base_dir).as_posix()
        return {
            "ok": True,
            "filename": fname,
            "rel_path": rel_path,         # relative to base_dir
            "size_bytes": size,
            "url_hint": f"/static/{self.subdir}/{fname}" if self.subdir else f"/static/{fname}",
        }

    def iter_files(self) -> Iterator[Tuple[str, int]]:
        """
        Yield (rel_path, size_bytes) for files under root (PDFs only).
        Used by /uploads listing endpoints.
        """
        for p in self.root.rglob("*.pdf"):
            if p.is_file():
                rel = p.relative_to(self.base_dir).as_posix()
                try:
                    size = p.stat().st_size
                except Exception:
                    size = 0
                yield (rel, size)

    def exists(self, rel_path: str) -> bool:
        return self._safe_path(rel_path).exists()

    def delete(self, rel_path: str) -> bool:
        p = self._safe_path(rel_path)
        if p.exists():
            p.unlink()
            return True
        return False

    def read_bytes(self, rel_path: str) -> bytes:
        p = self._safe_path(rel_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return p.read_bytes()
