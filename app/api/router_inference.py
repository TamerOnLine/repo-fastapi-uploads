# app/api/router_inference.py
from __future__ import annotations

import inspect
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from app.plugins.loader import get_plugin_instance  # integrate with your plugin system

router = APIRouter(prefix="/inference", tags=["inference"])


# --------- Models ---------
class InferenceRequest(BaseModel):
    plugin: str
    task: str
    payload: Dict[str, Any]


class InferenceResponse(BaseModel):
    ok: bool
    result: Dict[str, Any] | None = None
    error: str | None = None


# --------- Endpoints ---------
@router.get("/ping")
def ping():
    """Health check for the inference router"""
    return {"ok": True, "service": "inference"}


@router.post("/run", response_model=InferenceResponse)
async def run_inference(req: InferenceRequest = Body(...)):
    """
    Run inference by dynamically dispatching to a plugin + task.
    """
    if not req.plugin or not req.task:
        raise HTTPException(status_code=400, detail="Plugin and task are required")

    try:
        plugin = get_plugin_instance(req.plugin)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {req.plugin}")

    fn = getattr(plugin, req.task, None)
    if not callable(fn):
        raise HTTPException(status_code=404, detail=f"Task '{req.task}' not found in plugin '{req.plugin}'")

    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(req.payload)  # type: ignore
        else:
            result = fn(req.payload)  # type: ignore
    except Exception as e:
        return InferenceResponse(ok=False, error=f"Task failed: {e!s}")

    # Normalize result into dict
    if not isinstance(result, dict):
        result = {"result": result}

    return InferenceResponse(ok=True, result=result)
