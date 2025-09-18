from __future__ import annotations

import os
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

from app.main import app

# إن حدّدت NEUROSERVE_URL سنجرب الاتصال بسيرفر خارجي،
# وإلا سنستعمل TestClient داخل العملية.
BASE_URL = os.getenv("NEUROSERVE_URL")
API_KEY = os.getenv("NEUROSERVE_API_KEY")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _get(path: str):
    """
    طلب GET إمّا إلى سيرفر خارجي (إن كان محددًا ومتوفّرًا)،
    أو إلى TestClient داخليًا بدون الحاجة لتشغيل السيرفر يدويًا.
    """
    if BASE_URL:
        try:
            return requests.get(f"{BASE_URL}{path}", headers=_headers(), timeout=10)
        except requests.exceptions.RequestException as e:
            pytest.skip(f"External server not reachable: {e}")
    client = TestClient(app)
    return client.get(path, headers=_headers())


def _json_ok(method: str, path: str, **kwargs) -> Any:
    """
    مساعد عام لإرجاع JSON مع التأكد من كود الاستجابة 200.
    يُستخدم إن احتجت مستقبلاً نداءات POST/PUT… إلخ.
    """
    headers = kwargs.pop("headers", {}) or {}
    headers.update(_headers())

    if BASE_URL:
        try:
            r = requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=30, **kwargs)
        except requests.exceptions.RequestException as e:
            pytest.skip(f"External server not reachable: {e}")
    else:
        client = TestClient(app)
        r = client.request(method, path, headers=headers, **kwargs)

    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"
    return r.json()


def test_plugins_list() -> None:
    """
    يتحقق أن مسار /plugins يعمل ويرجع قائمة.
    """
    r = _get("/plugins")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)

    # تحقق أساسي من بنية كل عنصر
    for p in data:
        assert isinstance(p, dict)
        assert "name" in p
        # 'tasks' قد تكون غير موجودة أو قائمة فارغة حسب البلجن
        tasks = p.get("tasks")
        if tasks is not None:
            assert isinstance(tasks, list)


def test_plugins_detail_shape() -> None:
    """
    اختبار شكلي إضافي (اختياري) للتأكد من وجود مفاتيح شائعة إن وُجدت.
    إذا لم يكن هناك بلجنز، لن يفشل.
    """
    r = _get("/plugins")
    assert r.status_code == 200, r.text
    plugins = r.json()
    if not plugins:
        pytest.skip("No plugins registered")

    first = plugins[0]
    assert isinstance(first, dict)
    # مفاتيح اختيارية شائعة في مشروعك: name/provider/tasks
    assert "name" in first
    if "provider" in first:
        assert isinstance(first["provider"], (str, type(None)))
    if "tasks" in first and first["tasks"] is not None:
        assert isinstance(first["tasks"], list)


def test_plugins_detail_endpoint() -> None:
    """
    يتأكد من أن /plugins/{name} يعمل لكل Plugin (إن كان المسار مدعومًا).
    إذا لم يُنفّذ الراوتر هذا المسار يعامل كـ skip.
    """
    r = _get("/plugins")
    assert r.status_code == 200, r.text
    plugins = r.json()
    if not plugins:
        pytest.skip("No plugins registered")

    any_implemented = False
    for p in plugins:
        name = str(p.get("name", "")).strip()
        if not name:
            continue
        resp = _get(f"/plugins/{name}")
        if resp.status_code == 404:
            # قد لا يكون المسار مدعومًا في هذا التطبيق
            continue
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        # إن رجع اسم، تأكد أنه يطابق اسم البلجن
        if "name" in data:
            assert data["name"] == name
        any_implemented = True

    if not any_implemented:
        pytest.skip("Endpoint /plugins/{name} not implemented; skipping details test.")



