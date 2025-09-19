from __future__ import annotations

# أعد استخدام نفس التنفيذ الموجود بالخدمة
from app.services.pdf_reader.service import Plugin as _ServicePDFReaderPlugin


class Plugin(_ServicePDFReaderPlugin):
    """
    Thin wrapper to expose pdf_reader as a /plugins endpoint too.
    Reuses the exact extract_text implementation from the service.
    """

    # تأكيد الاسم والمهام لواجهة /plugins
    name = "pdf_reader"
    tasks = ["extract_text"]
