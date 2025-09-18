#!/usr/bin/env python3
"""
Generate docs/plugins-overview.md from plugins metadata and ensure per-plugin README.md files
and manifest.json (optional).

- Scans app/plugins/* for README.md, manifest.json, and plugin.py (tasks = [...]).
- Auto-creates README.md for any plugin missing it (or refreshes all with --force-readme).
- Auto-creates/updates manifest.json when requested (use --force-manifest to overwrite).
- Idempotent; safe to run anytime.

Usage:
    python tools/build_plugins_index.py
    python tools/build_plugins_index.py --force-readme
    python tools/build_plugins_index.py --force-manifest --force-readme
"""

from __future__ import annotations

import argparse
import ast
import json
import locale
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parents[1]  # project root
PLUGINS_DIR = ROOT / "app" / "plugins"
OUT_DIR = ROOT / "docs"
OUT_MD = OUT_DIR / "plugins-overview.md"
DOCS_PLUGINS_DIR = OUT_DIR / "plugins"

# For legacy regex extraction if needed (kept for backward compatibility)
TASKS_RE = re.compile(r"^\s*tasks\s*=\s*\[([^\]]*)\]", re.MULTILINE)
LIST_ITEM_RE = re.compile(r"['\"]([^'\"]+)['\"]")

# ---------------------------
# README template
# ---------------------------
README_TEMPLATE = """# {name}

**Provider:** {provider}
**Tasks:** {tasks_fmt}

## Description
Short description of what this plugin does and when to use it.

## Installation
- No extra dependencies beyond the project’s standard requirements, unless noted here.
- If this plugin needs additional models, weights, or external assets, list them here.

## Usage

### API Overview
- `GET /plugins` — lists all available plugins.
- `GET /plugins/{{name}}` — returns metadata for this plugin.
- `POST /plugins/{{name}}/{{task}}` — runs a task of this plugin.

> Replace `{{name}}` with this plugin’s folder name and `{{task}}` with one of the tasks listed above.

### cURL Example
```bash
curl -X POST "http://localhost:8000/plugins/{folder}/{example_task}" \\
     -H "Content-Type: application/json" \\
     -d '{example_payload_curl}'
```

### Python Example
```python
import requests

resp = requests.post(
    "http://localhost:8000/plugins/{folder}/{example_task}",
    json={example_payload_py},
    timeout=60,
)
print(resp.json())
```

## Notes
- If the plugin requires environment variables (e.g., HF_HOME, TORCH_HOME, TRANSFORMERS_OFFLINE), document them here.
- Add relevant reference links (model cards, docs) if applicable.
"""

@dataclass
class PluginMeta:
    folder: str
    name: str
    provider: str
    tasks: list[str]
    readme_rel: str | None
    manifest_rel: str | None
    plugin_rel: str | None
    example_payload_curl: str | None = None
    example_payload_py: str | None = None

def write_if_changed(path: Path, content: str, encoding: str = "utf-8") -> bool:
    """Write text file only if content changed. Returns True if written."""
    old = None
    if path.exists():
        try:
            old = path.read_text(encoding=encoding)
        except Exception:
            old = None
    if old == content:
        return False
    path.write_text(content, encoding=encoding)
    return True

def write_json_if_changed(path: Path, data: dict, *, indent: int = 2) -> bool:
    """Write JSON file only if content changed. Returns True if written."""
    new = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True)
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
            if old.strip() == new.strip():
                return False
        except Exception:
            pass
    path.write_text(new + "\n", encoding="utf-8")
    return True

def _supports_utf8() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "") or locale.getpreferredencoding(False) or ""
    enc_up = enc.upper()
    return "UTF-8" in enc_up or "UTF8" in enc_up

# Try to force UTF-8; if not possible, we’ll still have fallbacks.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Python ≥3.7
except Exception:
    pass

OK = "✅" if _supports_utf8() else "[OK]"
DOC = "📄" if _supports_utf8() else "[DOC]"
UPD = "📝" if _supports_utf8() else "[UPD]"

def read_tasks_from_plugin_ast(py_file: Path) -> list[str]:
    """
    Extract tasks via AST from plugin.py:

    class Plugin(AIPlugin):
        tasks = ["a", "b"]
    """
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Plugin":
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        if any(isinstance(t, ast.Name) and t.id == "tasks" for t in stmt.targets):
                            if isinstance(stmt.value, (ast.List, ast.Tuple)):
                                vals: list[str] = []
                                for elt in stmt.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        vals.append(elt.value)
                                return vals
        return []
    except Exception:
        return []

def read_tasks_from_plugin_regex(py_file: Path) -> list[str]:
    """Fallback: extract tasks list using regex."""
    try:
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        match = TASKS_RE.search(text)
        if not match:
            return []
        inside = match.group(1)
        return [task.strip() for task in LIST_ITEM_RE.findall(inside)]
    except Exception:
        return []

def read_manifest(manifest_file: Path) -> dict:
    try:
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

# ---------------------------
# Examples (per plugin)
# - Can also be provided via manifest.json as "example_payload"
# ---------------------------
DEFAULT_PAYLOAD_CURL = '{"input":"example"}'
DEFAULT_PAYLOAD_PY = "{'input': 'example'}"

EXAMPLE_PAYLOADS: dict[str, dict[str, str]] = {
    # pdf_reader expects a rel_path under UPLOAD_DIR
    "pdf_reader": {
        "curl": '{"rel_path":"pdf/<uuid>_file.pdf","return_text": true}',
        "py":   "{'rel_path': 'pdf/<uuid>_file.pdf', 'return_text': True}",
    },
}

def _escape_for_format(s: str) -> str:
    """Escape braces so str.format won't treat them as placeholders inside README_TEMPLATE.format."""
    return s.replace("{", "{{").replace("}", "}}")

def _example_payloads_for(folder: str, manifest: dict) -> tuple[str, str]:
    """
    Get (curl_example, py_example) for a plugin.
    Priority:
      1) manifest["example_payload"] (string) → used for both, with JSON→Py fix
      2) EXAMPLE_PAYLOADS[folder]
      3) defaults
    """
    # 1) From manifest (single JSON string)
    m_ex = manifest.get("example_payload")
    if isinstance(m_ex, str) and m_ex.strip():
        curl_ex = m_ex.strip()
        # naive JSON->Python literal tweaks (true/false/null and quotes)
        py_ex = (
            curl_ex
            .replace(" true", " True")
            .replace(": true", ": True")
            .replace(" false", " False")
            .replace(": false", ": False")
            .replace(" null", " None")
            .replace(": null", ": None")
            .replace('": "', "': '")
            .replace('", "', "', '")
            .replace('{"', "{'")
            .replace('"}', "'}")
        )
        return curl_ex, py_ex

    # 2) From hardcoded dict
    ex = EXAMPLE_PAYLOADS.get(folder)
    if ex:
        return ex.get("curl", DEFAULT_PAYLOAD_CURL), ex.get("py", DEFAULT_PAYLOAD_PY)

    # 3) Defaults
    return DEFAULT_PAYLOAD_CURL, DEFAULT_PAYLOAD_PY

def collect_plugins() -> list[PluginMeta]:
    plugins: list[PluginMeta] = []
    if not PLUGINS_DIR.exists():
        return plugins

    candidates = [
        p for p in PLUGINS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__"
    ]

    for pdir in sorted(candidates, key=lambda p: p.name.lower()):
        readme = pdir / "README.md"
        manifest = pdir / "manifest.json"
        plug_py = pdir / "plugin.py"

        # consider it a plugin only if plugin.py or manifest.json exists
        if not (plug_py.exists() or manifest.exists()):
            continue

        m = read_manifest(manifest) if manifest.exists() else {}

        name = m.get("name") or pdir.name
        provider = m.get("provider", "") or ""
        tasks: list[str] = []

        # prefer tasks from manifest
        if isinstance(m.get("tasks"), list):
            tasks = [str(x) for x in m["tasks"] if isinstance(x, (str, int, float))]
            tasks = [str(t).strip() for t in tasks if str(t).strip()]

        # otherwise try plugin.py via AST then regex
        if not tasks and plug_py.exists():
            tasks = read_tasks_from_plugin_ast(plug_py) or read_tasks_from_plugin_regex(plug_py)

        curl_ex, py_ex = _example_payloads_for(pdir.name, m)

        plugins.append(
            PluginMeta(
                folder=pdir.name,
                name=name,
                provider=provider,
                tasks=tasks,
                readme_rel=readme.relative_to(ROOT).as_posix() if readme.exists() else None,
                manifest_rel=manifest.relative_to(ROOT).as_posix() if manifest.exists() else None,
                plugin_rel=plug_py.relative_to(ROOT).as_posix() if plug_py.exists() else None,
                example_payload_curl=curl_ex,
                example_payload_py=py_ex,
            )
        )

    return plugins

def ensure_manifest(meta: PluginMeta, *, force: bool = False) -> bool:
    """
    Create/update app/plugins/<folder>/manifest.json
    - name/provider/version/tasks
    - example_payload (from EXAMPLE_PAYLOADS if not present)
    Returns True if the file was created/updated.
    """
    plug_dir = ROOT / "app" / "plugins" / meta.folder
    man_path = plug_dir / "manifest.json"

    # read current if exists
    current: dict = {}
    if man_path.exists():
        try:
            current = json.loads(man_path.read_text(encoding="utf-8"))
        except Exception:
            current = {}

    # tasks: prefer existing when not forcing; else use meta.tasks
    tasks: list[str] = []
    if isinstance(current.get("tasks"), list) and not force:
        tasks = [str(t).strip() for t in current["tasks"] if str(t).strip()]
    if not tasks:
        tasks = list(meta.tasks) if meta.tasks else []

    # basic fields
    name = current.get("name") if (current.get("name") and not force) else (meta.name or meta.folder)
    provider = current.get("provider") if (current.get("provider") and not force) else "local"
    version = current.get("version") if (current.get("version") and not force) else "0.1.0"

    # example payload: keep existing, else from EXAMPLE_PAYLOADS
    example_payload = current.get("example_payload")
    if not example_payload:
        ex = EXAMPLE_PAYLOADS.get(meta.folder)
        if ex and isinstance(ex.get("curl"), str):
            example_payload = ex["curl"]

    new_manifest = {
        "name": name,
        "provider": provider,
        "version": version,
        "tasks": tasks,
    }
    if example_payload:
        new_manifest["example_payload"] = example_payload

    # short-circuit if unchanged and not forcing
    if man_path.exists() and not force:
        base_cmp_keys = ["name", "provider", "version", "tasks", "example_payload"]
        same = all(current.get(k) == new_manifest.get(k) for k in base_cmp_keys)
        if same:
            return False

    return write_json_if_changed(man_path, new_manifest)

def render_readme(meta: PluginMeta) -> str:
    tasks_fmt = ", ".join(meta.tasks) if meta.tasks else "—"
    example_task = meta.tasks[0] if meta.tasks else "your-task"
    # escape braces inside the payloads so .format won't break them
    example_payload_curl = _escape_for_format(meta.example_payload_curl or DEFAULT_PAYLOAD_CURL)
    example_payload_py = _escape_for_format(meta.example_payload_py or DEFAULT_PAYLOAD_PY)
    return (
        README_TEMPLATE.format(
            name=meta.name,
            provider=meta.provider or "—",
            tasks_fmt=tasks_fmt,
            folder=meta.folder,
            example_task=example_task,
            example_payload_curl=example_payload_curl,
            example_payload_py=example_payload_py,
        ).rstrip()
        + "\n"
    )

def ensure_readme(meta: PluginMeta, force: bool = False) -> bool:
    """
    Create README.md if missing, or refresh it when --force-readme is set.
    Returns True if the file was created/updated.
    """
    readme_path = ROOT / "app" / "plugins" / meta.folder / "README.md"
    if readme_path.exists() and not force:
        return False
    content = render_readme(meta)
    return write_if_changed(readme_path, content, encoding="utf-8")

def render_markdown(plugins: list[PluginMeta]) -> str:
    lines = [
        "# 🔗 Plugins Index\n",
        "_Auto-generated. Do not edit manually._\n",
        "",
        "| Plugin | Provider | Tasks | README | manifest.json | plugin.py |",
        "|-------:|:---------|:------|:------:|:-------------:|:---------:|",
    ]

    for meta in plugins:
        tasks = ", ".join(meta.tasks) if meta.tasks else "—"
        readme_link = f"[README](../{meta.readme_rel})" if meta.readme_rel else "—"
        manifest_link = f"[manifest](../{meta.manifest_rel})" if meta.manifest_rel else "—"
        plugin_link = f"[plugin](../{meta.plugin_rel})" if meta.plugin_rel else "—"

        lines.append(
            f"| **{meta.name}** | {meta.provider or '—'} | `{tasks}` | "
            f"{readme_link} | {manifest_link} | {plugin_link} |"
        )

    lines += [
        "",
        "## How to generate",
        "```bash",
        "python tools/build_plugins_index.py",
        "```",
        "",
        "## Force-refresh all plugin READMEs",
        "```bash",
        "python tools/build_plugins_index.py --force-readme",
        "```",
        "",
        "## Force (re)generate manifest.json files",
        "```bash",
        "python tools/build_plugins_index.py --force-manifest",
        "```",
        "",
    ]

    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build plugins index and auto-generate per-plugin README and manifest.")
    parser.add_argument(
        "--force-readme",
        action="store_true",
        help="Regenerate README.md for all plugins even if they already exist.",
    )
    parser.add_argument(
        "--force-manifest",
        action="store_true",
        help="(Re)generate manifest.json for all plugins (overwrite common fields).",
    )
    args = parser.parse_args(argv)

    plugins = collect_plugins()

    # Create/refresh per-plugin manifest and README files
    created_readme = 0
    updated_readme = 0
    changed_manifest = 0

    for meta in plugins:
        # manifest first (so README can reference example_payload if manifest sets it)
        if ensure_manifest(meta, force=args.force_manifest):
            changed_manifest += 1

        changed = ensure_readme(meta, force=args.force_readme)
        if changed:
            if args.force_readme:
                updated_readme += 1
            else:
                created_readme += 1

    # Re-collect to capture new README/manifest paths for the index table
    plugins = collect_plugins()

    # Write overview
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_markdown(plugins), encoding="utf-8")

    print(f"{OK} Wrote {OUT_MD.relative_to(ROOT)} ({len(plugins)} plugins)")
    if created_readme:
        print(f"{DOC} Created {created_readme} README file(s)")
    if updated_readme:
        print(f"{UPD} Updated {updated_readme} README file(s)")
    if changed_manifest:
        print(f"{UPD} Created/Updated {changed_manifest} manifest.json file(s)")

    return 0

if __name__ == "__main__":
    sys.exit(main())
