from __future__ import annotations

from typing import Any

from app.plugins.base import AIPlugin


class Plugin(AIPlugin):
    name = "dummy"
    tasks = ["ping"]

    def load(self) -> None:
        return

    def ping(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"task": "ping", "payload_received": dict(payload or {})}

    def infer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"echo": dict(payload or {})}
