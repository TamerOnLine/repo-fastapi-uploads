# tools/generate_plugin_wrappers.py
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


# --- Paths --------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]  # project root
APP_DIR = ROOT / "app"
SERVICES_DIR = APP_DIR / "services"
PLUGINS_DIR = APP_DIR / "plugins"

# Ensure "app.*" is importable when this script runs directly
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- Utilities ----------------------------------------------------------


def write_text(path: Path, content: str) -> None:
    """
    Write text using UTF-8 and LF newlines (to avoid mixed-line-ending issues).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def discover_services() -> list[str]:
    """
    Find all services that have app/services/<name>/service.py
    """
    if not SERVICES_DIR.exists():
        return []
    names: list[str] = []
    for p in SERVICES_DIR.iterdir():
        if p.is_dir() and (p / "service.py").exists():
            names.append(p.name)
    return sorted(names)


def import_service_plugin(name: str) -> Any | None:
    """
    Try to import app.services.<name>.service and return class 'Plugin' if present.
    This import is only for build-time introspection; runtime wrapper is lazy.
    """
    mod_name = f"app.services.{name}.service"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        print(f"[WARN] cannot import service {name}: {e}")
        return None

    plugin_cls = getattr(mod, "Plugin", None)
    if plugin_cls is None:
        print(f"[WARN] service {name} has no class Plugin")
        return None
    return plugin_cls


def tasks_of(plugin_cls: Any) -> list[str]:
    """
    Extract 'tasks' from service.Plugin if available.
    """
    tasks = getattr(plugin_cls, "tasks", [])
    if isinstance(tasks, (list, tuple, set)):
        return [str(x) for x in tasks]
    return []


def regenerate_plugin_dir(target: Path, enabled: bool) -> None:
    """
    When enabled=True, remove target dir first, then recreate it.
    """
    if enabled and target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


# --- Generation ---------------------------------------------------------

LAZY_WRAPPER_TEMPLATE = """from __future__ import annotations
import importlib
from typing import Any, Dict
from app.plugins.base import AIPlugin

class Plugin(AIPlugin):
    # class-level defaults
    name = "{name}"
    tasks = {tasks}
    provider = "local"
    _impl = None  # instance of app.services.{name}.service.Plugin

    def __init__(self) -> None:
        # also set on instance to avoid loaders reading wrong defaults
        self.name = "{name}"
        self.tasks = list({tasks})

    def load(self) -> None:
        # Lazy import to avoid circular imports at startup
        if self._impl is None:
            mod = importlib.import_module("app.services.{name}.service")
            Impl = getattr(mod, "Plugin")
            self._impl = Impl()
            if hasattr(self._impl, "load"):
                self._impl.load()
            if not self.tasks:
                svc_tasks = getattr(self._impl, "tasks", [])
                if isinstance(svc_tasks, (list, tuple, set)):
                    self.tasks = list(svc_tasks)

    def __getattr__(self, item: str):
        # Proxy any task (e.g., extract_text) to the service implementation
        if item in self.tasks:
            def _call(payload: Dict[str, Any]):
                self.load()
                return getattr(self._impl, item)(payload)
            return _call
        raise AttributeError(item)
"""


def generate_one(name: str, *, force: bool, dry_run: bool) -> None:
    """
    Generate (or regenerate) app/plugins/<name>/ wrapper from app/services/<name>/service.py
    """
    plugin_dir = PLUGINS_DIR / name
    plugin_init = plugin_dir / "__init__.py"
    plugin_py = plugin_dir / "plugin.py"
    manifest_json = plugin_dir / "manifest.json"

    # Build-time tasks discovery (optional; wrapper is lazy at runtime)
    plugin_cls = import_service_plugin(name)
    tasks = tasks_of(plugin_cls) if plugin_cls is not None else []

    if dry_run:
        print(f"[DRY] would generate {name} with tasks={tasks}")
        return

    regenerate_plugin_dir(plugin_dir, enabled=force)

    # __init__.py
    write_text(plugin_init, "")

    # plugin.py (lazy adapter)
    tasks_repr = repr(tasks)  # مثال: [] أو ['extract_text']
    code = LAZY_WRAPPER_TEMPLATE.format(name=name, tasks=tasks_repr)
    write_text(plugin_py, code)

    # manifest.json
    manifest = {
        "name": name,
        "kind": "plugin",
        "folder": name,
        "provider": "local",
        "code": f"app/plugins/{name}/plugin.py",
        "tasks": tasks,
        "models": [],
    }
    write_text(manifest_json, json.dumps(manifest, ensure_ascii=False, indent=2))

    print(f"[OK] {'regenerated' if force else 'generated/updated'}: {name}")


# --- CLI ----------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate plugin wrappers from app/services/*/service.py (lazy adapters)."
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=[],
        help="Limit generation to specific service names (space-separated).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing app/plugins/<name>/ then regenerate from services.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without writing files.",
    )
    args = parser.parse_args()

    if not SERVICES_DIR.exists():
        print(f"[ERR] services dir not found: {SERVICES_DIR}")
        sys.exit(1)

    services = args.only if args.only else discover_services()
    if not services:
        print("[INFO] no services found.")
        return

    for name in services:
        generate_one(name, force=args.force, dry_run=args.dry_run)

    print("Wrappers generation complete ✅")


if __name__ == "__main__":
    main()
