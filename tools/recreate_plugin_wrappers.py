# tools/recreate_plugin_wrappers.py
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "app" / "services"
PLUGINS_DIR = ROOT / "app" / "plugins"

WRAPPER_TEMPLATE = """
from __future__ import annotations
import importlib
from typing import Any
from app.plugins.base import AIPlugin

class Plugin(AIPlugin):
    name = "__NAME__"
    tasks = __TASKS__
    provider = "local"
    _impl = None  # instance of app.services.__NAME__.service.Plugin

    def __init__(self) -> None:
        self.name = "__NAME__"
        self.tasks = list(__TASKS__)

    def load(self) -> None:
        if self._impl is None:
            mod = importlib.import_module("app.services.__NAME__.service")
            Impl = getattr(mod, "Plugin")
            self._impl = Impl()
            if hasattr(self._impl, "load"):
                self._impl.load()
        if not self.tasks and self._impl is not None:
            svc_tasks = getattr(self._impl, "tasks", [])
            if isinstance(svc_tasks, (list, tuple, set)):
                self.tasks = list(svc_tasks)

    def infer(self, payload: dict[str, Any]) -> Any:
        # generic fallback: dispatch by 'task' field
        self.load()
        task = (payload or {}).get("task")
        if isinstance(task, str) and hasattr(self._impl, task):
            return getattr(self._impl, task)(payload)
        raise AttributeError(f"Unknown task: {task!r}")

    def __getattr__(self, item: str):
        # ensure tasks are populated before checking
        self.load()
        if item in self.tasks and hasattr(self._impl, item):
            def _call(payload: dict[str, Any]):
                self.load()
                return getattr(self._impl, item)(payload)
            return _call
        raise AttributeError(item)
""".lstrip()


def discover_services() -> list[str]:
    names: list[str] = []
    if not SERVICES_DIR.exists():
        return names
    for d in SERVICES_DIR.iterdir():
        if d.is_dir() and (d / "service.py").exists():
            names.append(d.name)
    return sorted(names)


def tasks_of(service_name: str) -> list[str]:
    """Try to import service Plugin to read tasks at build-time (optional)."""
    try:
        mod = importlib.import_module(f"app.services.{service_name}.service")
        PluginCls = getattr(mod, "Plugin", None)
        if PluginCls is None:
            return []
        t = getattr(PluginCls, "tasks", [])
        if isinstance(t, (list, tuple, set)):
            return [str(x) for x in t]
    except Exception:
        pass
    return []


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # enforce LF to avoid mixed line endings
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def recreate_one(name: str) -> None:
    tasks = tasks_of(name)  # may be []
    pdir = PLUGINS_DIR / name
    p_py = pdir / "plugin.py"
    p_init = pdir / "__init__.py"
    manifest = pdir / "manifest.json"

    # clean directory (but keep folder)
    if pdir.exists():
        for f in pdir.iterdir():
            if f.is_file():
                f.unlink()
    else:
        pdir.mkdir(parents=True, exist_ok=True)

    code = WRAPPER_TEMPLATE.replace("__NAME__", name).replace("__TASKS__", repr(tasks))
    write_text(p_py, code)
    write_text(p_init, "")

    manifest_obj: dict[str, Any] = {
        "name": name,
        "kind": "plugin",
        "folder": name,
        "provider": "local",
        "code": f"app/plugins/{name}/plugin.py",
        "tasks": tasks,
        "models": [],
    }
    write_text(manifest, json.dumps(manifest_obj, ensure_ascii=False, indent=2))
    print(f"[OK] recreated wrapper: {name} (tasks={tasks or '[]'})")


def main() -> None:
    names = discover_services()
    if not names:
        print("[WARN] no services found under app/services/*")
        return
    for n in names:
        recreate_one(n)
    print("Recreation complete ✅")


if __name__ == "__main__":
    main()
