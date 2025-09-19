from __future__ import annotations

from app.services.pdf_reader.service import Plugin as _ServicePlugin


class Plugin(_ServicePlugin):
    name = "pdf_reader"
    tasks = ["extract_text"]
