# Plugin Wrappers — Quick Guide (AR)

> **TL;DR**: اكتب خدمتك في `app/services/<name>/service.py`، عرّف `Plugin` مع `name` و`tasks` والدوال المطلوبة. ثم شغّل سكربت إعادة إنشاء الـ wrappers ليولّد `app/plugins/<name>/plugin.py` تلقائيًا.

---

## 1) المتطلبات السريعة

* Python ≥ 3.10
* FastAPI + Starlette (موجودة بالمشروع)
* نظام المجلدات التالي:

  ```text
  app/
    api/
      router_plugins.py
    plugins/               # ملفات الـ wrappers (تتولّد تلقائيًا)
      <name>/
        plugin.py
        manifest.json
    services/              # تكتب خدمتك هنا
      <name>/
        service.py
  tools/
    recreate_plugin_wrappers.py    # سكربت توليد/إعادة توليد الـ wrappers
  ```

---

## 2) إنشاء خدمة جديدة (Service)

أنشئ ملف: `app/services/<name>/service.py`

### قالب جاهز

```python
from __future__ import annotations
from typing import Any, Dict, List

class Plugin:
    """خدمة محلية تُستهلك عبر الـ wrapper.

    - name: اسم الخدمة كما سيظهر في `/plugins`.
    - tasks: قائمة المهام التي تعرضها الخدمة (أسماء الدوال التي يمكن استدعاؤها عبر HTTP).
    - provider: اختياري. افتراضي "local".
    """

    name: str = "your_service_name"
    tasks: List[str] = ["ping"]  # غيّرها حسب مهامك
    provider: str = "local"

    def load(self) -> None:
        """اختياري: تهيئة ثقيلة/مؤجلة (تحميل نماذج، فتح ملفات، إلخ)."""
        pass

    # مثال لمهمة بسيطة
    def ping(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "echo": payload}

    # (اختياري) مسار تعويض إذا لم توجد دالة باسم المهمة
    # يسمح للراوتر ينادي: plugin.infer(task, payload)
    def infer(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if task in self.tasks and hasattr(self, task):
            return getattr(self, task)(payload)
        raise ValueError(f"Unknown task: {task}")
```

> **مهم:** لا تقم أبداً بعمل استيراد ذاتي داخل `service.py` (مثل `from app.services.<name>.service import Plugin`)، لأنه يسبب **circular import**.

---

## 3) توليد الـ Wrappers تلقائيًا

الـ wrappers تتولّد في `app/plugins/<name>/plugin.py` وتقوم بعمل **lazy import** لخدمتك من `app.services.<name>.service`.

### أوامر التوليد

* **Windows PowerShell**

  ```powershell
  # من جذر المشروع وبعد تفعيل venv
  python tools/recreate_plugin_wrappers.py
  ```
* **Bash**

  ```bash
  # من جذر المشروع وبعد تفعيل venv
  python tools/recreate_plugin_wrappers.py
  ```

سيُنشئ لكل خدمة موجودة تحت `app/services/*/service.py` مجلدًا مقابلًا تحت `app/plugins/<name>/` يحوي:

* `plugin.py` (الملف الفعلي للـ wrapper)
* `manifest.json` (وصف مختصر — يُنشأ تلقائيًا)

> لا حاجة لتعديل `plugin.py` يدويًا؛ عدّل منطقك داخل `service.py` فقط ثم أعد التوليد عند الحاجة.

---

## 4) كيف يعمل الاستدعاء عبر HTTP؟

يعرض الراوتر مسارًا عامًا: `POST /plugins/{name}/{task}`.

* يبحث عن الـ wrapper: `app/plugins/{name}/plugin.py`
* يقوم بتهيئة الكلاس `Plugin`، ثم **lazy import** لـ `app.services.{name}.service.Plugin`
* ينادي الدالة باسم `{task}` إن كانت ضمن `tasks` أو يحاول `infer(task, payload)`.

### مثال سريع (cURL)

```bash
curl -s -X POST http://localhost:8000/plugins/dummy/ping \
  -H "Content-Type: application/json" \
  -d '{"hello":"world"}'
```

### مثال بايثون (داخل المشروع)

```python
from app.main import app
from starlette.testclient import TestClient

c = TestClient(app)
r = c.post("/plugins/dummy/ping", json={"hello": "world"})
print(r.status_code, r.json())
```

---

## 5) اختبار كل شيء

```bash
pytest -q -m "not (gpu or gpu_cuda or gpu_mps)" --maxfail=1
```

> في حال خدمات اختيارية (مترجم، GPU…) قد ترى اختبارات `skipped` — هذا طبيعي.

---

## 6) ملاحظات مهمة

* **تجنّب الاستيرادات الدائرية:** لا تستورد `Plugin` من نفس `service.py`.
* **تحديث قائمة المهام:** تأكد أن `tasks` تعكس الأسماء الفعلية للدوال (مثل `extract_text`, `transcribe`…).
* **تهيئة مؤجلة:** ضع التحميل الثقيل داخل `load()`؛ سيتم استدعاؤها أول مرة فقط.
* **Line Endings:** على Windows قد تحتاج التأكد أن الملفات تحفظ بـ LF. الـ pre-commit hooks ستصححها تلقائيًا.
* **تنسيق/Lint:** `ruff` سيقوم بإصلاحات تلقائية أثناء الكومِت.

---

## 7) أخطاء شائعة وحلول

* **ImportError: partially initialized module**

  * السبب: استيراد ذاتي داخل `service.py`. الحل: احذف/عدّل الاستيراد، لا تستورد `Plugin` من ملفه.

* **404 على `/plugins/<name>/<task>`**

  * تحقق من وجود `app/plugins/<name>/plugin.py` (أعد التوليد)، وأن `task` موجود في `tasks` أو أن `infer` يسانده.

* **500 أثناء تنفيذ المهمة**

  * راجع الاستثناء في اللوج. غالبًا مشكلة فتح ملف، مسار غير صحيح، أو تهيئة غير ناجحة في `load()`.

---

## 8) مثال عملي لخدمة PDF بسيطة

```python
# app/services/pdf_reader/service.py
from __future__ import annotations
from typing import Any, Dict
from pathlib import Path

class Plugin:
    name = "pdf_reader"
    tasks = ["extract_text"]
    provider = "local"

    def load(self) -> None:
        # تهيئة اختيارية
        pass

    def extract_text(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rel_path = payload.get("rel_path")
        return_text = bool(payload.get("return_text", True))
        if not rel_path:
            return {"ok": False, "error": "rel_path is required"}
        # هنا منطق القراءة الحقيقي
        # لمثال بسيط، نرجّع نصًا فارغًا وعدد صفحات 0
        return {"ok": True, "rel_path": rel_path, "pages": 0, "text": ("" if return_text else None)}

    def infer(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if task in self.tasks and hasattr(self, task):
            return getattr(self, task)(payload)
        raise ValueError(f"Unknown task: {task}")
```

بعدها شغّل:

```bash
python tools/recreate_plugin_wrappers.py
```

ثم اختبر:

```bash
pytest -q -m "not (gpu or gpu_cuda or gpu_mps)" --maxfail=1
```

---

## 9) إضافة/تعديل مهام

* أضف اسم المهمة إلى `tasks` في خدمة `service.py`.
* أضف دالة بنفس الاسم `def my_task(self, payload: dict): ...`
* (اختياري) حدّث `infer` ليمرّر المهام تلقائيًا.
* أعد توليد الـ wrappers إذا احتجت.

---

## 10) أسئلة متكررة

**هل يجب تعديل `router_plugins.py`؟**
لا. الراوتر عام ويكتشف الـ plugins من نظام الملفات.

**هل أعدل `plugin.py` يدويًا؟**
لا. يولَّد تلقائيًا. عدّل منطقك في `service.py` فقط.

**كيف أضيف مزود خارجي (provider)؟**
ضبط `provider = "local"` اختياري للتوثيق فقط. المناداة تعتمد على المهام وليس على `provider`.

---

> جاهز لأي توسيع لاحق (EN version, examples with real PDF parsing, etc.).
