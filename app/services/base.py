from __future__ import annotations
from typing import Any, Dict

class CodeService:
    """
    Base for lightweight, code-only services (no heavy ML model loading).
    """
    name: str = "service"
    tasks: list[str] = []

    def load(self) -> None:
        # optional light init
        return

    def infer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # compatibility shim (not used directly; implement task methods instead)
        return {"ok": True}
