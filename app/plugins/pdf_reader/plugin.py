from __future__ import annotations

import importlib
from typing import Any

from app.plugins.base import AIPlugin


class Plugin(AIPlugin):
    # class-level defaults
    name = "pdf_reader"
    tasks = []
    provider = "local"
    _impl = None  # instance of app.services.pdf_reader.service.Plugin

    def __init__(self) -> None:
        # also set on instance to avoid loaders reading wrong defaults
        self.name = "pdf_reader"
        self.tasks = list([])

    def load(self) -> None:
        # Lazy import to avoid circular imports at startup
        if self._impl is None:
            mod = importlib.import_module("app.services.pdf_reader.service")
            Impl = mod.Plugin
            self._impl = Impl()
            if hasattr(self._impl, "load"):
                self._impl.load()
            if not self.tasks:
                svc_tasks = getattr(self._impl, "tasks", [])
                if isinstance(svc_tasks, (list, tuple, set)):
                    self.tasks = list(svc_tasks)

    def __getattr__(self, item: str):
        # Proxy any task (e.g., extract_text) to the service implementation
        if item in self.tasks:

            def _call(payload: dict[str, Any]):
                self.load()
                return getattr(self._impl, item)(payload)

            return _call
        raise AttributeError(item)
