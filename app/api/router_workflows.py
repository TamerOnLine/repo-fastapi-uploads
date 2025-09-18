# app/api/router_workflows.py
from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.plugins.loader import get_plugin_instance
from app.workflows import registry as wf


# اختياري: list_plugins (قد لا تكون متاحة في بعض الإصدارات)
try:
    from app.plugins.loader import list_plugins as _list_plugins  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _list_plugins = None  # fallback

router = APIRouter(prefix="/workflow", tags=["workflow"])


# =========================
# Models
# =========================
class Step(BaseModel):
    name: str = Field(..., min_length=1)
    plugin: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout: int | None = None  # optional per-step timeout (not enforced here)


class WorkflowRequest(BaseModel):
    sequence: list[Step] | None = None
    preset: str | None = None
    auto: bool = False

    inputs: dict[str, Any] | None = None
    audio_url: str | None = None
    language: str | None = None
    max_new_tokens: int | None = 256

    return_: str | None = Field(default=None, alias="return")


# =========================
# Presets (examples)
# =========================
PRESETS: dict[str, list[Step]] = {
    "arabic_asr_plus": [
        Step(
            name="asr",
            plugin="whisper",
            task="speech-to-text",
            payload={
                "audio_url": "{audio_url}",
                "language": None,  # auto-detect
                "max_new_tokens": 256,
                "postprocess": True,
            },
            timeout=180,
        ),
    ],
}


# =========================
# Helpers
# =========================
def _lookup_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _inject_placeholders(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _inject_placeholders(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_inject_placeholders(v, context) for v in value]
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        key = value[1:-1]
        # top-level inputs
        if key in context.get("_root_", {}):
            return context["_root_"][key]
        # dotted step.field
        if "." in key:
            step_name, path = key.split(".", 1)
            step_obj = context.get(step_name)
            if isinstance(step_obj, dict):
                return _lookup_path(step_obj, path)
        # raw step name
        return context.get(key)
    return value


def _build_auto_sequence(req: WorkflowRequest) -> list[Step]:
    if req.audio_url:
        return [
            Step(
                name="asr",
                plugin="whisper",
                task="speech-to-text",
                payload={
                    "audio_url": "{audio_url}",
                    "language": req.language,
                    "max_new_tokens": req.max_new_tokens or 256,
                    "postprocess": True,
                },
                timeout=180,
            )
        ]
    raise HTTPException(status_code=400, detail="auto mode requires 'audio_url' (or provide a preset/sequence)")


def _resolve_sequence(req: WorkflowRequest) -> tuple[list[Step], str | None]:
    if req.sequence:
        return (list(req.sequence), None)

    if req.preset:
        # from filesystem first
        try:
            wf_def = wf.get_workflow(req.preset)  # dict loaded from workflow.json
            steps = [Step(**s) for s in wf_def.get("sequence", [])]
            ret = wf_def.get("return")
            return (steps, ret)
        except Exception:
            pass  # fallback to in-code presets

        steps = PRESETS.get(req.preset)
        if not steps:
            raise HTTPException(status_code=404, detail=f"Preset '{req.preset}' not found")
        return ([Step(**s.model_dump()) for s in steps], None)

    if req.auto or req.audio_url:
        return (_build_auto_sequence(req), None)

    raise HTTPException(
        status_code=400,
        detail="Provide one of: 'sequence', 'preset', or 'auto' (with suitable inputs).",
    )


def _get_available_plugins() -> set[str]:
    if _list_plugins is None:
        return set()
    try:
        reg = _list_plugins()
    except Exception:
        return set()
    if isinstance(reg, dict):
        return set(reg.keys())
    if isinstance(reg, (list, tuple, set)):  # runtime isinstance → tuple أنواع
        return set(reg)
    return set()


def _validate_sequence(seq: list[Step]) -> None:
    available = _get_available_plugins()
    if not available:
        return
    for i, st in enumerate(seq, 1):
        if not st.plugin or st.plugin not in available:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"Plugin '{st.plugin}' not found at step #{i}",
                    "available_plugins": sorted(available),
                },
            )


async def _run_step(step: Step, context: dict[str, Any]) -> dict[str, Any]:
    try:
        plugin = get_plugin_instance(step.plugin)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Plugin '{step.plugin}' not found") from e

    tasks = getattr(plugin, "tasks", None)
    if callable(tasks):
        try:
            tasks = tasks()
        except Exception:
            tasks = None
    if isinstance(tasks, (list, tuple, set)) and step.task not in tasks:
        raise HTTPException(status_code=400, detail=f"Plugin '{step.plugin}' does not support task '{step.task}'")

    root_inputs = dict(context.get("_root_", {}))
    payload = _inject_placeholders(step.payload, {**context, "_root_": root_inputs})

    try:
        # prefer direct task if exposed; else fallback to infer
        fn = getattr(plugin, step.task, None)
        if callable(fn):
            if inspect.iscoroutinefunction(fn):
                result = await fn(payload)  # type: ignore[misc]
            else:
                result = fn(payload)  # type: ignore[misc]
        else:
            infer_fn = getattr(plugin, "infer", None)
            if not callable(infer_fn):
                raise HTTPException(status_code=404, detail=f"Task '{step.task}' not found on plugin '{step.plugin}'")
            if inspect.iscoroutinefunction(infer_fn):
                result = await infer_fn({**payload, "task": step.task})  # type: ignore[misc]
            else:
                result = infer_fn({**payload, "task": step.task})  # type: ignore[misc]
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Step '{step.name}' failed: {err!s}") from err

    return result if isinstance(result, dict) else {"result": result}


# =========================
# Routes
# =========================
@router.get("/ping")
def workflow_ping() -> dict[str, Any]:
    return {"ok": True}


@router.get("/presets")
def list_presets():
    file_presets: list[str] = []
    try:
        file_presets = [w["name"] for w in wf.list_workflows()]
    except Exception:
        pass
    code_presets = list(PRESETS.keys())
    return {"ok": True, "presets": sorted(set(file_presets + code_presets))}


@router.post("/run")
async def run_workflow(req: WorkflowRequest) -> dict[str, Any]:
    """
    Run a workflow via explicit `sequence`, `preset` (filesystem or in-code), or `auto`.
    Supports placeholders like "{audio_url}" or "{asr.text}".
    """
    sequence, preset_return = _resolve_sequence(req)
    _validate_sequence(sequence)

    target_return = req.return_ or preset_return

    root_context: dict[str, Any] = {}
    if req.inputs:
        root_context.update(req.inputs)
    if req.audio_url is not None:
        root_context["audio_url"] = req.audio_url
    if req.language is not None:
        root_context["language"] = req.language
    if req.max_new_tokens is not None:
        root_context["max_new_tokens"] = req.max_new_tokens

    context: dict[str, Any] = {"_root_": root_context}
    results: list[dict[str, Any]] = []

    if not sequence:
        raise HTTPException(status_code=400, detail="Empty workflow sequence.")

    for step in sequence:
        out = await _run_step(step, context)
        context[step.name] = out
        results.append({"step": step.name, "plugin": step.plugin, "task": step.task, "output": out})

    if target_return:
        for r in results:
            if r["step"] == target_return:
                return {"ok": True, "result": r["output"]}

        raise HTTPException(status_code=400, detail=f"return target '{target_return}' not found in steps")

    return {"ok": True, "count": len(results), "results": results}
