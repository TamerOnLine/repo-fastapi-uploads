# tests/test_pdf_translate.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

from app.main import app


# يدعم:
# - اختبار داخل العملية (TestClient)
# - أو ضد سيرفر حي عبر NEUROSERVE_URL
BASE_URL = os.getenv("NEUROSERVE_URL")
API_KEY = os.getenv("NEUROSERVE_API_KEY")  # إن فعّلت API Key
TRANSLATOR = os.getenv("TRANSLATOR_PLUGIN", "")  # مثلاً: translator_m2m أو text_tools

CLIENT = None if BASE_URL else TestClient(app)
SAMPLE_PDF = Path("docs/sample.pdf")
assert SAMPLE_PDF.exists(), "docs/sample.pdf not found"


def _request(method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {}) or {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    if BASE_URL:
        return requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=60, **kwargs)
    return CLIENT.request(method, path, headers=headers, **kwargs)  # type: ignore[arg-type]


def _json_ok(method: str, path: str, **kwargs) -> dict[str, Any]:
    r = _request(method, path, **kwargs)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"
    return r.json()  # type: ignore[return-value]


def _list_plugins() -> list[dict[str, Any]]:
    data = _json_ok("GET", "/plugins")
    assert isinstance(data, list)
    return data


def _find_plugin_with_task(task_name: str) -> str | None:
    t = task_name.lower()
    for p in _list_plugins():
        tasks = [str(x).lower() for x in (p.get("tasks") or [])]
        if t in tasks:
            return str(p["name"])
    return None


def _extract_text_field(payload: dict[str, Any]) -> str:
    # يدعم شكلين: {"text": "..."} أو {"result": {"text": "..."}}
    if isinstance(payload.get("text"), str):
        return payload["text"]
    result = payload.get("result")
    if isinstance(result, dict):
        val = result.get("text") or result.get("content")
        if isinstance(val, str):
            return val
    return ""


@pytest.mark.integration
def test_pdf_reader_then_translate():
    # 1) رفع الـ PDF
    with SAMPLE_PDF.open("rb") as f:
        files = {"file": ("sample.pdf", f, "application/pdf")}
        up = _request("POST", "/uploads/pdf", files=files)
    assert up.status_code in (200, 201), up.text
    up_j = up.json()
    assert up_j.get("ok") is True
    rel_path = up_j["rel_path"]

    pdf_reader = _find_plugin_with_task("extract_text") or "pdf_reader"
    xt = _json_ok(
        "POST",
        f"/plugins/{pdf_reader}/extract_text",
        json={"rel_path": rel_path, "return_text": True},
    )
    text = _extract_text_field(xt)
    assert text.strip(), "Empty text extracted from PDF"

    # 3) الترجمة عبر أي Plugin يعرّف مهمة translate (أو المحدد بالبيئة)
    translator = TRANSLATOR or _find_plugin_with_task("translate")
    if not translator:
        pytest.skip("No translator plugin exposing 'translate' task found")

    tr = _json_ok(
        "POST",
        f"/plugins/{translator}/translate",
        json={"text": text[:5000], "source_lang": "auto", "target_lang": "ar"},
    )
    translation = _extract_text_field(tr) or tr.get("translation")
    assert isinstance(translation, str) and translation.strip()
