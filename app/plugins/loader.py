# app/plugins/loader.py
from __future__ import annotations

import importlib
import json
import pkgutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


# ----------------------------
# Registry & lightweight proxy
# ----------------------------

REGISTRY: dict[str, Any] = {}  # name -> plugin instance OR ManifestProxy
MANIFESTS: dict[str, dict] = {}  # name -> manifest dict
_DISCOVERED = False  # guard so we don't rediscover repeatedly


@dataclass
class ManifestProxy:
    """
    Lightweight metadata used by /plugins to avoid importing heavy plugin code.
    Provides name/provider/tasks attributes that the router expects.
    """

    name: str
    provider: str | None = None
    tasks: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tasks is None:
            self.tasks = []


# ----------------------------
# Internal helpers
# ----------------------------


def _plugins_package() -> ModuleType:
    """Return the app.plugins package module."""
    return importlib.import_module("app.plugins")


def _read_manifest(pkg_name: str) -> dict:
    """
    Read <package>/manifest.json if present.
    Returns {} if not found or invalid.
    """
    try:
        pkg = importlib.import_module(pkg_name)
        pkg_path = Path(getattr(pkg, "__file__", "")).parent
        mf = pkg_path / "manifest.json"
        if mf.is_file():
            return json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _discover_once() -> None:
    """Scan app.plugins.* subpackages and register ManifestProxy for each."""
    global _DISCOVERED
    if _DISCOVERED:
        return

    base_pkg = _plugins_package()
    for m in pkgutil.iter_modules(base_pkg.__path__, base_pkg.__name__ + "."):
        # Consider any direct subpackage as a plugin candidate
        short = m.name.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue

        manifest = _read_manifest(m.name)
        name = manifest.get("name") or short
        provider = manifest.get("provider")
        tasks = manifest.get("tasks")
        if isinstance(tasks, (list, tuple, set)):
            tasks_list = [str(t) for t in tasks]
        else:
            tasks_list = []

        # Register a ManifestProxy (no plugin.py import yet)
        if name not in REGISTRY:
            REGISTRY[name] = ManifestProxy(name=name, provider=provider, tasks=tasks_list)
        MANIFESTS[name] = manifest

    _DISCOVERED = True


def _materialize_plugin(name: str) -> Any | None:
    """
    Load and return the real plugin object:
    - Prefer app.plugins.<name>.plugin
    - If it defines class Plugin -> instantiate; otherwise return the module itself.
    """
    try:
        mod = importlib.import_module(f"app.plugins.{name}.plugin")
    except Exception:
        # No plugin.py within the package
        return None

    # If a Plugin class exists, instantiate it; otherwise the module acts as the plugin.
    plugin_cls = getattr(mod, "Plugin", None)
    if plugin_cls is not None:
        try:
            inst = plugin_cls()  # type: ignore[call-arg]
        except Exception:
            # Fallback to the module if instantiation fails
            return mod

        # Call optional load()
        load_fn = getattr(inst, "load", None)
        if callable(load_fn):
            try:
                load_fn()
            except Exception:
                pass

        # Ensure a name attribute
        if not getattr(inst, "name", None):
            try:
                inst.name = name
            except Exception:
                pass
        return inst

    # No class; use the module as the plugin
    if not getattr(mod, "name", None):
        try:
            mod.name = name
        except Exception:
            pass

    # If no tasks attribute, fall back to manifest tasks
    if not isinstance(getattr(mod, "tasks", None), (list, tuple, set)):
        mf = MANIFESTS.get(name) or {}
        mtasks = mf.get("tasks")
        if isinstance(mtasks, (list, tuple, set)):
            try:
                mod.tasks = [str(t) for t in mtasks]
            except Exception:
                pass

    return mod


# ----------------------------
# Public API expected by routers
# ----------------------------


def ensure_plugins_loaded() -> None:
    """Idempotent discovery used by routes on first access."""
    _discover_once()


def list_plugins() -> dict:
    """
    Return registry of manifests for OpenAPI enrichment.
    Dict[name] -> manifest (may be empty if not present).
    """
    ensure_plugins_loaded()
    # Return a shallow copy to avoid external mutation
    return {k: dict(v or {}) for k, v in MANIFESTS.items()}


def available_plugin_names() -> list[str]:
    ensure_plugins_loaded()
    return sorted(REGISTRY.keys())


def iter_plugins() -> Iterable[Any]:
    """
    Yield lightweight proxies (ManifestProxy) or real plugin instances
    if they were already materialized via get_plugin_instance/load_plugin.
    """
    ensure_plugins_loaded()
    return list(REGISTRY.values())


def get_plugin_instance(name: str) -> Any | None:
    """
    Return a concrete plugin object (module or instance).
    Materialize on first access and cache it in REGISTRY.
    """
    ensure_plugins_loaded()
    if name in REGISTRY and not isinstance(REGISTRY[name], ManifestProxy):
        return REGISTRY[name]

    real = _materialize_plugin(name)
    if real is not None:
        REGISTRY[name] = real
        return real
    return None


def load_plugin(name: str) -> Any | None:
    """Alias for get_plugin_instance for API compatibility."""
    return get_plugin_instance(name)


# Backward-compat names some routers might look for
get_plugins = iter_plugins
available_plugins = available_plugin_names
list_available_plugins = available_plugin_names
resolve_plugin = get_plugin_instance
