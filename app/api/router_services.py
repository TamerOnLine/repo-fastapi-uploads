# app/api/router_services.py
from __future__ import annotations

import inspect
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/services", tags=["services"])


# ---------- Discovery helpers ----------
def _services_dir() -> Path:
    # app/api/ -> parents[1] = app/
    return Path(__file__).resolve().parents[1] / "services"


def _discover_services() -> dict[str, dict[str, str]]:
    """
    Return { service_name: {folder: name, module: 'app.services.<name>.service'} }
    """
    base = _services_dir()
    out: dict[str, dict[str, str]] = {}
    if not base.exists():
        return out
    for d in base.iterdir():
        if d.is_dir() and (d / "service.py").exists():
            out[d.name] = {"folder": d.name, "module": f"app.services.{d.name}.service"}
    return out


def _get_service(name: str):
    """
    Import app.services.<name>.service and build Service().
    Calls .load() if present (lightweight init).
    """
    meta = _discover_services().get(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Service not found: {name}")

    try:
        mod = import_module(meta["module"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import service '{name}': {e}") from e

    svc_cls = getattr(mod, "Service", None)
    if svc_cls is None:
        raise HTTPException(status_code=500, detail=f"Service module '{name}' missing class Service")

    try:
        inst = svc_cls()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to construct service '{name}': {e}") from e

    load_fn = getattr(inst, "load", None)
    if callable(load_fn):
        try:
            load_fn()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Service '{name}' failed to load: {e}") from e

    return inst


# ---------- Models (optional but useful for docs) ----------
class ServiceMeta(BaseModel):
    name: str
    tasks: list[str] = []
    type: str = "service"


# ---------- Routes ----------
@router.get("/", response_model=dict[str, list[str]])
def list_services() -> dict[str, list[str]]:
    """List all available code-only services."""
    return {"services": sorted(_discover_services().keys())}


@router.get("/{name}", response_model=ServiceMeta)
def service_meta(name: str) -> ServiceMeta:
    """Return basic metadata for a service (name, tasks, type)."""
    inst = _get_service(name)
    tasks_attr = getattr(inst, "tasks", [])
    tasks = list(tasks_attr) if isinstance(tasks_attr, (list, tuple, set)) else []
    return ServiceMeta(name=getattr(inst, "name", name), tasks=tasks)


@router.post("/{name}/{task}")
async def call_service(
    name: str,
    task: str,
    payload: dict[str, Any] = Body(..., description="Arbitrary JSON payload for the service task."),
) -> dict[str, Any]:
    """
    Invoke a code-only service task.
    - If the task attribute is async -> await it.
    - If sync -> call it directly.
    """
    inst = _get_service(name)

    if not hasattr(inst, task):
        raise HTTPException(status_code=404, detail=f"Task '{task}' not found in service '{name}'")

    fn = getattr(inst, task)
    if not callable(fn):
        raise HTTPException(status_code=500, detail=f"Task '{task}' in service '{name}' is not callable")

    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(payload)  # type: ignore[misc]
        else:
            result = fn(payload)  # type: ignore[misc]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Service '{name}.{task}' failed: {e}") from e

    # Ensure a dict-like response for consistency
    if isinstance(result, (list, tuple, set)):
        result = list(result)
    if not isinstance(result, dict):
        return {"ok": True, "result": result}

    return result
