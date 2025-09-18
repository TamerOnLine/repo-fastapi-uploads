#!/usr/bin/env python3
"""
Build docs for plugins & services, and ensure per-item README.md + manifest.json.

- Sources:
    * Plugins  -> app/plugins/<name>/plugin.py   (class Plugin)
    * Services -> app/services/<name>/service.py (class Service)
                  (fallback: plugin.py with class Plugin)

- Extracted via AST (if present on the class):
    * tasks: list[str]
    * REQUIRED_MODELS: list[ {repo/model keys...} ]
    * EXAMPLE_PAYLOAD: str (JSON-like)
    * provider: str
    * class docstring -> used as description

- Outputs:
    * docs/plugins-overview.md
    * docs/services-overview.md
    * docs/plugins/<name>/README.md          (plugins)
    * app/services/<name>/README.md          (services)  <-- as requested
    * app/plugins/<name>/manifest.json       (if --force-manifest / --update-all)
    * app/services/<name>/manifest.json      (if --force-manifest / --update-all)

Flags:
    --force-readme     Regenerate README for all items (overwrite)
    --force-manifest   Create/overwrite manifest.json for all items
    --update-all       Shorthand for both flags
    --only             Limit to 'plugins' or 'services'
    --verbose          Print per-item actions
"""

from __future__ import annotations

import argparse
import ast
import json
import locale
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


# ---------------------------
# Paths
# ---------------------------
ROOT = Path(__file__).resolve().parents[1]  # project root
PLUGINS_DIR = ROOT / "app" / "plugins"
SERVICES_DIR = ROOT / "app" / "services"
OUT_DIR = ROOT / "docs"
OUT_PLUGINS_DIR = OUT_DIR / "plugins"
OUT_SERVICES_DIR = OUT_DIR / "services"
OUT_PLUGINS_MD = OUT_DIR / "plugins-overview.md"
OUT_SERVICES_MD = OUT_DIR / "services-overview.md"


# ---------------------------
# stdout unicode helpers
# ---------------------------
def _supports_utf8() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "") or locale.getpreferredencoding(False) or ""
    enc_up = enc.upper()
    return "UTF-8" in enc_up or "UTF8" in enc_up


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Python ≥3.7
except Exception:
    pass

OK = "✅" if _supports_utf8() else "[OK]"
DOC = "📄" if _supports_utf8() else "[DOC]"
UPD = "📝" if _supports_utf8() else "[UPD]"
ERR = "❌" if _supports_utf8() else "[ERR]"


# ---------------------------
# Data models
# ---------------------------
@dataclass
class ItemMeta:
    kind: Literal["plugin", "service"]
    folder: str
    class_name: str  # "Plugin" or "Service"
    base_dir: Path  # PLUGINS_DIR or SERVICES_DIR
    code_file: Path  # plugin.py or service.py
    manifest_file: Path  # app/.../manifest.json
    readme_file: Path  # docs/.../<name>/README.md (plugins) | app/services/<name>/README.md
    name: str  # display name (defaults to folder)
    provider: str | None
    tasks: list[str]
    description: str
    models: list[dict] | None
    example_payload: str | None


# ---------------------------
# IO helpers
# ---------------------------
def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_if_changed(path: Path, content: str, encoding: str = "utf-8") -> bool:
    old = None
    if path.exists():
        try:
            old = path.read_text(encoding=encoding)
        except Exception:
            old = None
    if old == content:
        return False
    ensure_dir(path.parent)
    path.write_text(content, encoding=encoding)
    return True


def write_json_if_changed(path: Path, data: dict, *, indent: int = 2) -> bool:
    new = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True)
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
            if old.strip() == new.strip():
                return False
        except Exception:
            pass
    ensure_dir(path.parent)
    path.write_text(new + "\n", encoding="utf-8")
    return True


# ---------------------------
# AST readers
# ---------------------------
def _parse_ast(py_file: Path) -> ast.AST | None:
    try:
        return ast.parse(py_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_class(tree: ast.AST | None, class_name: str) -> ast.ClassDef | None:
    if not tree:
        return None
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _read_class_attr_list_of_str(cls: ast.ClassDef, attr: str) -> list[str]:
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == attr for t in stmt.targets):
                if isinstance(stmt.value, (ast.List, ast.Tuple)):
                    vals: list[str] = []
                    for elt in stmt.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            vals.append(elt.value)
                    return vals
    return []


def _read_class_attr_list_of_dict(cls: ast.ClassDef, attr: str) -> list[dict]:
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == attr for t in stmt.targets):
                if isinstance(stmt.value, (ast.List, ast.Tuple)):
                    items: list[dict] = []
                    for elt in stmt.value.elts:
                        if isinstance(elt, ast.Dict):
                            d: dict[str, Any] = {}
                            for k, v in zip(elt.keys, elt.values, strict=False):
                                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                    if isinstance(v, ast.Constant):
                                        d[k.value] = v.value
                            if d:
                                items.append(d)
                    return items
    return []


def _read_class_attr_str(cls: ast.ClassDef, attr: str) -> str | None:
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == attr for t in stmt.targets):
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    return stmt.value.value.strip()
    return None


def _read_docstring(cls: ast.ClassDef | None) -> str:
    if not cls:
        return ""
    return (ast.get_docstring(cls) or "").strip()


# ---------------------------
# Path helpers
# ---------------------------
def _readme_path_for(kind: str, base_dir: Path, out_dir: Path, folder: str) -> Path:
    if kind == "plugin":
        return base_dir / folder / "README.md"
    return base_dir / folder / "README.md"


# ---------------------------
# Collectors
# ---------------------------
def discover_items(kind: Literal["plugin", "service"]) -> list[ItemMeta]:
    if kind == "plugin":
        base = PLUGINS_DIR
        class_name_preferred = "Plugin"
        candidates = ["plugin.py"]  # plugins must have plugin.py
        out_dir = OUT_PLUGINS_DIR
    else:
        base = SERVICES_DIR
        class_name_preferred = "Service"
        # accept service.py (preferred) OR plugin.py (fallback) for services
        candidates = ["service.py", "plugin.py"]
        out_dir = OUT_SERVICES_DIR

    items: list[ItemMeta] = []
    if not base.exists():
        return items

    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        code_file = None
        for fname in candidates:
            f = d / fname
            if f.exists():
                code_file = f
                break
        if not code_file:
            continue

        tree = _parse_ast(code_file)
        # For services: prefer class Service, fallback to Plugin
        cls = _find_class(tree, class_name_preferred) or _find_class(tree, "Plugin")

        tasks = _read_class_attr_list_of_str(cls, "tasks") if cls else []
        models = _read_class_attr_list_of_dict(cls, "REQUIRED_MODELS") if cls else []
        example_payload = _read_class_attr_str(cls, "EXAMPLE_PAYLOAD") if cls else None
        provider = _read_class_attr_str(cls, "provider") if cls else None
        description = _read_docstring(cls)

        name = d.name  # default
        maybe_name = _read_class_attr_str(cls, "name") if cls else None
        if maybe_name:
            name = maybe_name

        manifest_file = d / "manifest.json"
        readme_file = _readme_path_for(kind, base, out_dir, d.name)

        items.append(
            ItemMeta(
                kind=kind,
                folder=d.name,
                class_name=class_name_preferred,
                base_dir=base,
                code_file=code_file,
                manifest_file=manifest_file,
                readme_file=readme_file,
                name=name,
                provider=provider,
                tasks=tasks,
                description=description,
                models=models or None,
                example_payload=example_payload,
            )
        )
    return items


# ---------------------------
# Rendering
# ---------------------------
README_TEMPLATE = """# {name}

**Type:** {kind}
**Provider:** {provider}
**Tasks:** {tasks_fmt}

{description}

## Models
{models_block}

## Usage

### API Overview
- `GET /{base}` — list all available {kind_plural}.
- `GET /{base}/{{name}}` — get metadata for this {kind}.
- `POST /{base}/{{name}}/{{task}}` — run a task of this {kind}.

> Replace `{{name}}` with this {kind}'s folder name and `{{task}}` with one of the tasks listed above.

### cURL Example
```bash
curl -X POST "http://localhost:8000/{base}/{folder}/{example_task}" \
     -H "Content-Type: application/json" \
     -d '{example_payload_curl}'
```

### Python Example
```python
import requests

resp = requests.post(
    "http://localhost:8000/{base}/{folder}/{example_task}",
    json={example_payload_py},
    timeout=60,
)
print(resp.json())
```

## Notes
- If this {kind} requires environment variables (e.g., HF_HOME, TORCH_HOME, TRANSFORMERS_OFFLINE), document them here.
- Add relevant reference links (model cards, docs) if applicable.
"""


def format_models_block(models: list[dict] | None) -> str:
    if not models:
        return "- _None_"
    lines: list[str] = []
    for m in models:
        repo = m.get("repo") or m.get("repo_id") or m.get("model") or ""
        if isinstance(repo, str) and "/" in repo:
            lines.append(f"- [{repo}](https://huggingface.co/{repo})")
        else:
            safe = json.dumps(m, ensure_ascii=False)
            lines.append(f"- {safe}")
    return "\n".join(lines)


def render_readme(it: ItemMeta) -> str:
    base = "plugins" if it.kind == "plugin" else "services"
    kind_plural = "plugins" if it.kind == "plugin" else "services"
    tasks_fmt = ", ".join(it.tasks) if it.tasks else "_infer_"
    example_task = it.tasks[0] if it.tasks else "infer"

    if it.example_payload:
        try:
            parsed = json.loads(it.example_payload)
            example_payload_curl = json.dumps(parsed, ensure_ascii=False)
            example_payload_py = example_payload_curl
        except Exception:
            example_payload_curl = it.example_payload.replace("\n", " ")
            example_payload_py = example_payload_curl
    else:
        example_payload_curl = "{}"
        example_payload_py = "{}"

    return README_TEMPLATE.format(
        name=it.name or it.folder,
        kind=it.kind,
        provider=it.provider or "_unknown_",
        tasks_fmt=tasks_fmt,
        description=it.description or "",
        models_block=format_models_block(it.models),
        base=base,
        kind_plural=kind_plural,
        folder=it.folder,
        example_task=example_task,
        example_payload_curl=example_payload_curl,
        example_payload_py=example_payload_py,
    )


def render_overview_md(kind: Literal["plugin", "service"], items: list[ItemMeta]) -> str:
    title = "Plugins Overview" if kind == "plugin" else "Services Overview"
    hdr = f"# {title}\n\nTotal: **{len(items)}**\n\n"
    hdr += "| Name | Folder | Provider | Tasks | Files |\n"
    hdr += "|------|--------|----------|-------|-------|\n"
    lines: list[str] = []
    for it in items:
        tasks_fmt = ", ".join(it.tasks) if it.tasks else "_infer_"
        # README may live under docs/ (plugins) OR app/services (services) -> always make link relative to ROOT
        readme_rel = it.readme_file.relative_to(ROOT).as_posix()
        code_rel = it.code_file.relative_to(ROOT).as_posix()
        manifest_rel = it.manifest_file.relative_to(ROOT).as_posix()
        files_links = f"[README]({readme_rel}) · [code]({code_rel}) · [manifest]({manifest_rel})"
        lines.append(f"| {it.name} | `{it.folder}` | {it.provider or '-'} | {tasks_fmt} | {files_links} |")
    return hdr + "\n".join(lines) + "\n"


# ---------------------------
# Writers
# ---------------------------
def write_readmes(items: list[ItemMeta], *, force: bool, verbose: bool) -> tuple[int, int]:
    created = 0
    updated = 0
    for it in items:
        content = render_readme(it)
        existed = it.readme_file.exists()
        if write_if_changed(it.readme_file, content):
            if existed:
                updated += 1
                if verbose:
                    print(f"{UPD} Updated README: {it.readme_file}")
            else:
                created += 1
                if verbose:
                    print(f"{DOC} Created README: {it.readme_file}")
        elif force and existed:
            if verbose:
                print(f"{OK} README unchanged: {it.readme_file}")
    return created, updated


def write_manifests(items: list[ItemMeta], *, force: bool, verbose: bool) -> int:
    changed = 0
    for it in items:
        data = {
            "name": it.name or it.folder,
            "provider": it.provider,
            "tasks": it.tasks or ["infer"],
            "models": it.models or [],
            "example_payload": it.example_payload or "{}",
            "kind": it.kind,
            "folder": it.folder,
            "code": it.code_file.relative_to(ROOT).as_posix(),
        }
        if force or not it.manifest_file.exists():
            if write_json_if_changed(it.manifest_file, data):
                changed += 1
                if verbose:
                    print(f"{UPD} Wrote manifest: {it.manifest_file}")
        else:
            if write_json_if_changed(it.manifest_file, data):
                changed += 1
                if verbose:
                    print(f"{UPD} Updated manifest: {it.manifest_file}")
    return changed


# ---------------------------
# Main
# ---------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build index/docs for plugins & services.")
    parser.add_argument("--force-readme", action="store_true", help="Regenerate README.md for all items.")
    parser.add_argument("--force-manifest", action="store_true", help="Create/overwrite manifest.json for all items.")
    parser.add_argument("--update-all", action="store_true", help="Shortcut for --force-readme + --force-manifest")
    parser.add_argument("--only", choices=["plugins", "services"], help="Limit to a single source type.")
    parser.add_argument("--verbose", action="store_true", help="Verbose output.")
    args = parser.parse_args(argv)

    if args.update_all:
        args.force_readme = True
        args.force_manifest = True

    # Prepare output dirs for plugins/docs and services/docs (overview pages)
    ensure_dir(OUT_PLUGINS_DIR)
    ensure_dir(OUT_SERVICES_DIR)

    items_plugins: list[ItemMeta] = []
    items_services: list[ItemMeta] = []

    if args.only in (None, "plugins"):
        items_plugins = discover_items("plugin")
    if args.only in (None, "services"):
        items_services = discover_items("service")

    cr_p, up_p = (0, 0)
    cr_s, up_s = (0, 0)
    if args.only in (None, "plugins"):
        cr_p, up_p = write_readmes(items_plugins, force=args.force_readme, verbose=args.verbose)
    if args.only in (None, "services"):
        cr_s, up_s = write_readmes(items_services, force=args.force_readme, verbose=args.verbose)

    changed_over_p = write_if_changed(OUT_PLUGINS_MD, render_overview_md("plugin", items_plugins))
    changed_over_s = write_if_changed(OUT_SERVICES_MD, render_overview_md("service", items_services))

    man_p = man_s = 0
    if args.force_manifest:
        if args.only in (None, "plugins"):
            man_p = write_manifests(items_plugins, force=True, verbose=args.verbose)
        if args.only in (None, "services"):
            man_s = write_manifests(items_services, force=True, verbose=args.verbose)
    else:
        if args.only in (None, "plugins"):
            man_p = write_manifests(items_plugins, force=False, verbose=args.verbose)
        if args.only in (None, "services"):
            man_s = write_manifests(items_services, force=False, verbose=args.verbose)

    total_items = len(items_plugins) + len(items_services)
    print(f"{OK} Indexed {total_items} item(s): {len(items_plugins)} plugin(s), {len(items_services)} service(s).")
    print(f"{DOC} READMEs  -> created {cr_p + cr_s}, updated {up_p + up_s}.")
    print(
        f"{DOC} Overviews-> plugins({'updated' if changed_over_p else 'unchanged'}), services({'updated' if changed_over_s else 'unchanged'})."  # noqa: E501
    )
    if args.force_manifest:
        print(f"{DOC} Manifests-> created/updated {man_p + man_s}.")
    else:
        print(f"{DOC} Manifests-> updated-if-changed {man_p + man_s} (no create).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
