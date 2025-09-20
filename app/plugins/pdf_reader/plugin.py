from __future__ import annotations

import importlib
from typing import Any

from app.plugins.base import AIPlugin


class Plugin(AIPlugin):
    name = "pdf_reader"
    tasks = []
    provider = "local"
    _impl = None  # instance of app.services.pdf_reader.service.Plugin

    def __init__(self) -> None:
        self.name = "pdf_reader"
        self.tasks = list([])

    def load(self) -> None:
        if self._impl is None:
            mod = importlib.import_module("app.services.pdf_reader.service")
            Impl = mod.Plugin
            self._impl = Impl()
            if hasattr(self._impl, "load"):
                self._impl.load()
        if not self.tasks and self._impl is not None:
            svc_tasks = getattr(self._impl, "tasks", [])
            if isinstance(svc_tasks, (list, tuple, set)):
                self.tasks = list(svc_tasks)

    def infer(self, payload: dict[str, Any]) -> Any:
        # generic fallback: dispatch by 'task' field
        self.load()
        task = (payload or {}).get("task")
        if isinstance(task, str) and hasattr(self._impl, task):
            return getattr(self._impl, task)(payload)
        raise AttributeError(f"Unknown task: {task!r}")

    def __getattr__(self, item: str):
        # ensure tasks are populated before checking
        self.load()
        if item in self.tasks and hasattr(self._impl, item):

            def _call(payload: dict[str, Any]):
                self.load()
                return getattr(self._impl, item)(payload)

            return _call
        raise AttributeError(item)
