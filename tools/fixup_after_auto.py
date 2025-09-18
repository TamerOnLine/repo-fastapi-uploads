#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DUP_TARGETS = [
    ROOT / "app" / "api" / "router_auth.py",
    ROOT / "app" / "api" / "router_inference.py",
    ROOT / "app" / "api" / "router_uploads.py",
    ROOT / "app" / "services" / "pdf_reader" / "service.py",
]

NOQA_LONG_LINES = [
    ROOT / "tools" / "auto_patch_ruff_fixes.py",
    ROOT / "tools" / "build_plugins_index.py",
]


def fix_from_e_dup(p: Path) -> None:
    if not p.exists():
        return
    s = p.read_text(encoding="utf-8")
    # نظّف أي تكرار مثل: " from efrom e", أو " from e from e"
    s = s.replace(" from efrom e", " from e")
    s = s.replace(" from e from e", " from e")
    p.write_text(s, encoding="utf-8")
    print(f"Fixed 'from e' duplication: {p}")


def add_noqa_for_long_lines(p: Path, limit: int = 120) -> None:
    if not p.exists():
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    changed = False
    for i, line in enumerate(lines):
        if len(line) > limit and "noqa" not in line:
            lines[i] = f"{line}  # noqa: E501"
            changed = True
    if changed:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Added noqa to long lines: {p}")
    else:
        print(f"No long lines (or already noqa): {p}")


def main():
    for p in DUP_TARGETS:
        fix_from_e_dup(p)
    for p in NOQA_LONG_LINES:
        add_noqa_for_long_lines(p)


if __name__ == "__main__":
    main()
