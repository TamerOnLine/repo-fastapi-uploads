from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any


class AIPlugin(ABC):
    """
    Base class for all plugins.
    Optional extension points for dynamic prefetch:
      - REQUIRED_MODELS: list[dict]  e.g. {"type":"hf","id":"facebook/bart-large-cnn"}
      - def prefetch(self) -> None
      - def required_models(self) -> Iterable[dict]
    """

    name: str = "unknown"
    tasks: list[str] = []

    # Optional: static declarations of needed models
    REQUIRED_MODELS: list[dict] = []

    @abstractmethod
    def load(self) -> None:
        """Load heavy resources lazily when the plugin is first used."""
        ...

    @abstractmethod
    def infer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Default/primary task (legacy). Many plugins define task methods instead."""
        ...

    # Optional: dynamic list of required models
    def required_models(self) -> Iterable[dict]:
        return list(getattr(self, "REQUIRED_MODELS", []) or [])

    # Optional: plugin-specific prefetch hook
    def prefetch(self) -> None:
        """Download/cache models ahead of time. Override if needed."""
        return
