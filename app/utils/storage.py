from __future__ import annotations

import contextlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile


class LocalStorage:
    """
    تخزين محلي على القرص مع تحقق أساسي لملفات PDF وحجمها.
    """
    def __init__(self, base_dir: Path, subdir: str = "pdf", max_mb: int = 20):
        self.base_dir = Path(base_dir)
        self.subdir = subdir
        self.max_bytes = int(max_mb) * 1024 * 1024

    def _ensure_dir(self) -> Path:
        target = self.base_dir / self.subdir
        target.mkdir(parents=True, exist_ok=True)
        return target

    async def save_pdf(self, upload: UploadFile) -> dict:
        if not upload or not upload.filename:
            raise HTTPException(status_code=400, detail="No file uploaded")

        # اسم الملف الأصلي (مع تعقيم)
        original_name = Path(upload.filename).name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name) or "file.pdf"

        # تحقق سريع من ترويسة PDF بدون تحميل الملف كاملًا في الذاكرة
        head = upload.file.read(5)
        upload.file.seek(0)
        if head != b"%PDF-":
            raise HTTPException(status_code=400, detail="Invalid PDF (missing %PDF- header).")

        # كتابة على القرص بتدفق (chunks) + فحص الحجم
        dest_dir = self._ensure_dir()
        dest = dest_dir / f"{uuid4().hex}_{safe_name}"

        total = 0
        CHUNK = 1024 * 1024  # 1MB
        try:
            with dest.open("wb") as out:
                while True:
                    chunk = upload.file.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large (> {self.max_bytes // (1024*1024)} MB).",
                        )
        except HTTPException:
            with contextlib.suppress(Exception):
                dest.unlink(missing_ok=True)
            raise
        finally:
            with contextlib.suppress(Exception):
                upload.file.close()

        # relative path مفيد للتعامل لاحقًا
        rel_path = str(Path(self.subdir) / dest.name)
        return {
            "filename": safe_name,
            "stored_as": dest.name,
            "path": str(dest),
            "rel_path": rel_path,
            "size_bytes": total,
        }
