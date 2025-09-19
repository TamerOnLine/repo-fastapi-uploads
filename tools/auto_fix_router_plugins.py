# tools/auto_fix_router_plugins.py
from __future__ import annotations

from pathlib import Path


ROUTER_PATH = Path(__file__).resolve().parents[1] / "app" / "api" / "router_plugins.py"
ROUTER_PATH.parent.mkdir(parents=True, exist_ok=True)

CONTENT = """from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path as FPath, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Ruff B008-safe Body default
BODY_JSON: dict = Body(...)

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginMeta(BaseModel):
    name: str
    provider: str | None = None
    tasks: list[str] = Field(default_factory=list)


def _loader_module():
    \"\"\"Import app.plugins.loader and best-effort call any init function if present.\"\"\"
    mod = importlib.import_module("app.plugins.loader")
    for fn_name in (
        "ensure_plugins_loaded",
        "load_all_plugins",
        "load_plugins",
        "init_plugins",
        "initialize",
        "discover_plugins",
    ):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                pass
    return mod


def _instantiate_direct(name: str) -> Any | None:
    \"\"\"Strict filesystem fallback: import app.plugins.<name>.plugin:Plugin and instantiate.\"\"\"
    try:
        mod = importlib.import_module(f"app.plugins.{name}.plugin")
    except Exception:
        return None

    plugin_cls = getattr(mod, "Plugin", None)
    if plugin_cls is None:
        return None

    try:
        inst = plugin_cls()  # type: ignore[call-arg]
    except Exception:
        return None

    try:
        load_fn = getattr(inst, "load", None)
        if callable(load_fn):
            load_fn()
    except Exception:
        pass

    if not getattr(inst, "name", None):
        try:
            inst.name = name
        except Exception:
            pass

    return inst


def _get_plugin_instance(name: str) -> Any | None:
    \"\"\"Prefer direct instantiation first (works with lazy wrappers), then use loader.\"
    \"\"\"
    inst = _instantiate_direct(name)
    if inst is not None:
        return inst

    loader = _loader_module()

    for fn_name in ("get_plugin_instance", "load_plugin", "get", "resolve_plugin"):
        fn = getattr(loader, fn_name, None)
        if callable(fn):
            try:
                inst = fn(name)
                if inst is not None:
                    return inst
            except Exception:
                pass

    for reg_name in ("REGISTRY", "PLUGINS", "plugins", "registry"):
        reg = getattr(loader, reg_name, None)
        if isinstance(reg, dict) and name in reg:
            return reg[name]

    return None


def _iter_plugin_instances() -> Iterable[Any]:
    \"\"\"Return iterable of instances (normalize any strings via _get_plugin_instance).\"\"\"
    loader = _loader_module()

    def _normalize(seq):
        for x in seq:
            if isinstance(x, str):
                inst = _get_plugin_instance(x)
                if inst is not None:
                    yield inst
            elif x is not None:
                yield x

    # 1) functions that return plugins
    for name in (
        "get_available_plugins",
        "list_available_plugins",
        "available_plugins",
        "get_plugins",
        "iter_plugins",
    ):
        fn = getattr(loader, name, None)
        if callable(fn):
            try:
                plugins = fn()
                if isinstance(plugins, dict):
                    return _normalize(plugins.values())
                if isinstance(plugins, (list, tuple, set)):
                    return _normalize(plugins)
                if plugins:
                    return _normalize(plugins)
            except Exception:
                pass

    # 2) registries
    for reg_name in ("REGISTRY", "PLUGINS", "plugins", "registry"):
        reg = getattr(loader, reg_name, None)
        if isinstance(reg, dict) and reg:
            return _normalize(reg.values())
        if isinstance(reg, (list, tuple)) and reg:
            return _normalize(reg)

    # 3) names -> instances
    for name_api in ("get_plugin_names", "list_plugin_names", "available_plugin_names"):
        fn = getattr(loader, name_api, None)
        if callable(fn):
            try:
                names = fn()
                if names:
                    return _normalize(names)
            except Exception:
                pass

    return ()


RESERVED_PLUGIN_DIRS = {"base", "loader", "module", "__pycache__", ".pytest_cache"}


def _discover_plugins_filesystem() -> list[Any]:
    base = Path(__file__).resolve().parents[2] / "app" / "plugins"
    instances: list[Any] = []
    if not base.exists():
        return instances
    for d in sorted(p.name for p in base.iterdir() if p.is_dir()):
        if d in RESERVED_PLUGIN_DIRS:
            continue
        if not (base / d / "plugin.py").exists():
            continue
        inst = _instantiate_direct(d)
        if inst is not None:
            instances.append(inst)
    return instances


def _dedupe_by_name(instances: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for inst in instances:
        nm = getattr(inst, "name", None)
        if not nm or nm in seen:
            continue
        seen.add(nm)
        out.append(inst)
    return out


def _serialize_meta(plugin: Any) -> PluginMeta:
    name = getattr(plugin, "name", None) or getattr(
        getattr(plugin, "__class__", None), "__name__", "unknown"
    )
    provider = getattr(plugin, "provider", None)
    tasks_attr = getattr(plugin, "tasks", None)
    tasks = list(tasks_attr) if isinstance(tasks_attr, (list, tuple, set)) else []
    return PluginMeta(name=str(name), provider=provider, tasks=tasks)


@router.get("/ping")
def ping() -> dict[str, Any]:
    return {"ok": True, "service": "plugins"}


@router.get("", response_model=list[PluginMeta], summary="List all plugins")
def list_plugins() -> list[PluginMeta]:
    fs_instances = _discover_plugins_filesystem()
    loader_instances: list[Any] = []
    for item in _iter_plugin_instances():
        if isinstance(item, str):
            inst = _get_plugin_instance(item)
            if inst is not None:
                loader_instances.append(inst)
        elif item is not None:
            loader_instances.append(item)
    instances = _dedupe_by_name(fs_instances + loader_instances)
    return [_serialize_meta(p) for p in instances]


@router.get("/{name}", response_model=PluginMeta, summary="Get plugin metadata")
def get_plugin(name: Annotated[str, FPath(min_length=1)]) -> PluginMeta:
    for inst in _iter_plugin_instances():
        meta = _serialize_meta(inst)
        if meta.name == name:
            return meta
    inst = _get_plugin_instance(name)
    if inst is not None:
        return _serialize_meta(inst)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plugin not found: {name}")


def _make_task_handler(PluginCls: type, task_name: str):
    def handler(payload: dict[str, Any] = BODY_JSON):
        inst = PluginCls()
        load_fn = getattr(inst, "load", None)
        if callable(load_fn):
            try:
                load_fn()
            except Exception:
                pass
        fn = getattr(inst, task_name, None)
        if not callable(fn):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{task_name}' not found.",
            )
        return fn(payload or {})
    return handler


@router.post(
    "/{name}/{task}",
    summary="Run a task of a plugin",
    description="Executes a task for a given plugin with an arbitrary JSON payload.",
)
async def run_plugin_task(
    name: Annotated[str, FPath(min_length=1)],
    task: Annotated[str, FPath(min_length=1)],
    payload: dict[str, Any] = BODY_JSON,
) -> JSONResponse:
    plugin = _get_plugin_instance(name)
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {name}",
        )

    declared_tasks = getattr(plugin, "tasks", [])
    fn = getattr(plugin, task, None)

    if callable(fn):
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(payload)  # type: ignore[misc]
            else:
                result = fn(payload)  # type: ignore[misc]
            return JSONResponse({"plugin": name, "task": task, "result": result})
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task '{task}' failed: {e!s}",
            ) from e

    infer_fn = getattr(plugin, "infer", None)
    if callable(infer_fn):
        forwarded = dict(payload)
        forwarded.setdefault("task", task)
        try:
            if inspect.iscoroutinefunction(infer_fn):
                result = await infer_fn(forwarded)  # type: ignore[misc]
            else:
                result = infer_fn(forwarded)  # type: ignore[misc]
            return JSONResponse({"plugin": name, "task": task, "result": result})
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Infer for '{task}' failed: {e!s}",
            ) from e

    available = list(declared_tasks) if isinstance(declared_tasks, (list, tuple, set)) else []
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Task '{task}' not found in plugin '{name}'. Available: {available or ['<none>']}",
    )

# Backward-compatible alias
plugins = router
"""


def main() -> None:
    # enforce LF newlines
    text = CONTENT.replace("\\r\\n", "\\n")
    ROUTER_PATH.write_text(text, encoding="utf-8")
    print(f"[OK] Wrote {ROUTER_PATH}")


if __name__ == "__main__":
    main()
