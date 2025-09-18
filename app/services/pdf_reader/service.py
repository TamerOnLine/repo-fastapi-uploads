from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.core.config import get_settings
from app.plugins.base import AIPlugin  # واجهة الإضافات عندك
from fastapi import HTTPException

# سنستخدم pdfminer لاستخراج النص، و pypdf لعدد الصفحات (سريع وموثوق)
from pdfminer.high_level import extract_text
from pypdf import PdfReader


class Plugin(AIPlugin):
    name = "pdf_reader"
    tasks = ["extract_text"]

    def _resolve_path(self, payload: Dict[str, Any]) -> Path:
        """
        يبني المسار بأمان إما من rel_path (مفضل) أو path مطلق.
        نتأكد أنه داخل UPLOAD_DIR فقط (حماية من path traversal).
        """
        settings = get_settings()
        base = Path(settings.UPLOAD_DIR).resolve()

        rel = payload.get("rel_path")
        p = payload.get("path")

        if rel:
            target = (base / rel).resolve()
        elif p:
            target = Path(p).resolve()
        else:
            raise HTTPException(status_code=400, detail="Provide 'rel_path' or 'path' to the PDF.")

        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found.")

        # منع الخروج خارج مجلد الرفع
        if not str(target).startswith(str(base)):
            raise HTTPException(status_code=400, detail="Access outside uploads is not allowed.")

        # فحص سريع للترويسة
        with target.open("rb") as f:
            if f.read(5) != b"%PDF-":
                raise HTTPException(status_code=400, detail="Invalid PDF header.")

        return target

    def extract_text(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        المدخلات:
          - rel_path: "pdf/<stored_name>" (مفضل) أو path مطلق داخل uploads
          - max_pages: (اختياري) حد أقصى لعدد الصفحات (0 أو None = الكل)
          - return_text: (اختياري) افتراضي True — رجّع النص
        """
        max_pages = payload.get("max_pages", None)
        return_text_flag = payload.get("return_text", True)

        pdf_path = self._resolve_path(payload)

        # احصائيات سريعة: عدد الصفحات
        try:
            reader = PdfReader(str(pdf_path))
            total_pages = len(reader.pages)
        except Exception:
            total_pages = None

        # استخراج النص
        try:
            if max_pages and isinstance(max_pages, int) and max_pages > 0:
                # pdfminer لا يدعم slice مباشر بسهولة؛ نقرأ كامل الملف ونقص لاحقًا إن لزم
                text = extract_text(str(pdf_path))
                # (اختياري) يمكن لاحقًا تقطيع حسب فواصل صفحات إن احتجنا
            else:
                text = extract_text(str(pdf_path))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")

        result = {
            "ok": True,
            "plugin": self.name,
            "task": "extract_text",
            "file": str(pdf_path),
            "pages": total_pages,
            "text_len": len(text) if text else 0,
        }
        if return_text_flag:
            result["text"] = text

        return result
