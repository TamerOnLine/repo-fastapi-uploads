from __future__ import annotations

from pathlib import Path
from typing import Any

from app.plugins.base import AIPlugin


try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None


class Plugin(AIPlugin):
    name = "pdf_reader"
    provider = "local"
    tasks = ["extract_text"]

    def load(self) -> None:
        # لا شيء مطلوب الآن
        pass

    def infer(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        # مجرد stub لإرضاء الـ ABC
        return {"ok": True, "service": self.name}

    # ---- helpers ----
    def _resolve_path(self, rel_path: str) -> Path:
        p = Path(rel_path)
        if p.is_file():
            return p
        candidates = [
            Path("uploads") / rel_path,
            Path("app") / "uploads" / rel_path,
            Path("data") / "uploads" / rel_path,
        ]
        for q in candidates:
            if q.is_file():
                return q
        # fallback
        return Path("uploads") / rel_path

    # ---- tasks ----
    def extract_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        rel = (payload or {}).get("rel_path")
        return_text = bool((payload or {}).get("return_text"))
        if not rel:
            return {"ok": False, "error": "rel_path is required"}

        path = self._resolve_path(rel)
        if not path.exists():
            return {"ok": False, "rel_path": rel, "error": f"file not found: {rel}"}

        out: dict[str, Any] = {"ok": True, "rel_path": rel}
        pages = 0
        text = ""

        if PdfReader is not None:
            try:
                with open(path, "rb") as f:
                    reader = PdfReader(f)
                    pages = len(reader.pages)
                    if return_text:
                        parts: list[str] = []
                        for page in reader.pages:
                            try:
                                parts.append(page.extract_text() or "")
                            except Exception:
                                parts.append("")
                        text = "\n".join(parts)
            except Exception as e:
                out["warning"] = f"PdfReader failed: {e!s}"

        out["pages"] = pages
        if return_text:
            out["text"] = text
        return out
