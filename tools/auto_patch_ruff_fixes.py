#!/usr/bin/env python3
"""
Auto-fix a subset of Ruff findings that are not auto-fixable:
- B008: FastAPI Depends/Body/File via typing.Annotated
- B904: "raise ... from e"
- E501: specific long lines we know
- E402: move 'from app.plugins import loader' to top in scripts/prefetch_models.py

The script targets EXACT patterns seen in your report.
Run from repo root:  python tools/auto_patch_ruff_fixes.py
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def ensure_annotated_import(text: str) -> str:
    if re.search(r"\bfrom\s+typing\s+import\s+Annotated\b", text):
        return text
    # Insert Annotated import next to other typing imports or after __future__
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:20]):
        if re.match(r"\s*from\s+typing\s+import\b", line):
            insert_at = i + 1
            break
        if re.match(r"\s*import\s+typing\b", line):
            insert_at = i + 1
            break
        if line.startswith("from __future__ import"):
            insert_at = i + 1
    lines.insert(insert_at, "from typing import Annotated")
    return "\n".join(lines)


def fix_b904_simple(text: str) -> str:
    # Add ' from e' to raise HTTPException(...) where the except is "as e"
    # Pattern 1: except Something as e:  (.*)\n\s*raise HTTPException(...)
    def repl_block(m: re.Match) -> str:
        block = m.group(0)
        # Add ' from e' to the first raise HTTPException(...) in this block if not present
        block = re.sub(
            r"raise\s+HTTPException\(([^)]*)\)\s*$", r"raise HTTPException(\1) from e", block, flags=re.MULTILINE
        )
        return block

    text = re.sub(
        r"(except\s+[A-Za-z_][\w\.]*\s+as\s+e:\n(?:[^\n]*\n){0,6}?\s*raise\s+HTTPException\([^\n]*\)\s*)",
        repl_block,
        text,
        flags=re.MULTILINE,
    )
    return text


def fix_router_auth(p: Path):
    s = read(p)
    # B904 specific line
    s = s.replace(
        'raise HTTPException(status_code=401, detail=f"Invalid token: {e}")',
        'raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e',
    )
    # B008 -> Annotated for login/me
    s = ensure_annotated_import(s)
    s = re.sub(
        r"def\s+login\(\s*form:\s*OAuth2PasswordRequestForm\s*=\s*Depends\(\)\s*\)\s*:",
        r"def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):",
        s,
    )
    s = re.sub(
        r"def\s+me\(\s*user:\s*User\s*=\s*Depends\(\s*get_current_user\s*\)\s*\)\s*:",
        r"def me(user: Annotated[User, Depends(get_current_user)]):",
        s,
    )
    write(p, s)


def fix_router_inference(p: Path):
    s = read(p)
    s = ensure_annotated_import(s)
    # B008 Body(...)
    s = re.sub(
        r"async\s+def\s+run_inference\(\s*req:\s*InferenceRequest\s*=\s*Body\(\.\.\.\)\s*\)\s*:",
        r"async def run_inference(req: Annotated[InferenceRequest, Body(...)]):",
        s,
    )
    # B904 plugin not found
    s = re.sub(
        r"except\s+Exception:\s*\n\s*raise\s+HTTPException\(",
        "except Exception as e:\n        raise HTTPException(",
        s,
    )
    # add ' from e' if missing right after HTTPException(...)
    s = re.sub(
        r"(raise\s+HTTPException\([^\n]*\))\s*$",
        r"\1 from e",
        s,
        flags=re.MULTILINE,
    )
    write(p, s)


def fix_router_services(p: Path):
    s = read(p)
    s = ensure_annotated_import(s)
    # B008 Body(...) for payload annot
    s = re.sub(
        r"payload:\s*dict\[str,\s*Any\]\s*=\s*Body\(\.\.\.,\s*description=\"Arbitrary JSON payload for the service task\.\"\),",  # noqa: E501
        'payload: Annotated[dict[str, Any], Body(..., description="Arbitrary JSON payload for the service task.")],',
        s,
    )
    write(p, s)


def fix_router_uploads(p: Path):
    s = read(p)
    s = ensure_annotated_import(s)
    # B008 File(...)
    s = re.sub(
        r"async\s+def\s+upload_pdf\(\s*file:\s*UploadFile\s*=\s*File\(\.\.\.\)\s*\)\s*->\s*UploadResult:",
        r"async def upload_pdf(file: Annotated[UploadFile, File(...)]) -> UploadResult:",
        s,
    )
    # B904 two places
    s = s.replace(
        'raise HTTPException(status_code=500, detail=f"Failed to save PDF: {e}")',
        'raise HTTPException(status_code=500, detail=f"Failed to save PDF: {e}") from e',
    )
    s = s.replace(
        "raise HTTPException(status_code=400, detail=str(e))",
        "raise HTTPException(status_code=400, detail=str(e)) from e",
    )
    write(p, s)


def fix_router_workflows(p: Path):
    s = read(p)
    # E501 the exact long line -> wrap
    s = s.replace(
        "raise HTTPException(status_code=400, detail=\"Provide one of: 'sequence', 'preset', or 'auto' (with suitable inputs).\")",  # noqa: E501
        "raise HTTPException(\n"
        "        status_code=400,\n"
        "        detail=\"Provide one of: 'sequence', 'preset', or 'auto' (with suitable inputs).\",\n"
        "    )",
    )
    write(p, s)


def fix_services_pdf_reader(p: Path):
    s = read(p)
    s = s.replace(
        'raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")',
        'raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}") from e',
    )
    write(p, s)


def fix_scripts_prefetch_models(p: Path):
    s = read(p)
    # Ensure top import exists
    if "from app.plugins import loader" not in s.splitlines()[:30]:
        # put it after __future__ or docstring
        # simple: insert after first triple-quote block if present, else at top
        if '"""' in s:
            first = s.find('"""')
            second = s.find('"""', first + 3)
            if second != -1:
                s = s[: second + 3] + "\n\nfrom app.plugins import loader\n" + s[second + 3 :]
        else:
            s = "from app.plugins import loader\n" + s
    # Remove later duplicate import line
    s = re.sub(r"^\s*from\s+app\.plugins\s+import\s+loader\s*#.*?$", "", s, flags=re.MULTILINE)
    write(p, s)


def fix_tools_build_plugins_index(p: Path):
    s = read(p)
    # E501 long logger line -> switch to parameterized multi-line
    s = re.sub(
        r'logger\.info\(f"plugins\(\{\s*\'updated\'\s*if\s*changed_over_p\s*else\s*\'unchanged\'\s*\}\),\s*services\(\{\s*\'updated\'\s*if\s*changed_over_s\s*else\s*\'unchanged\'\s*\}\)\."\)',  # noqa: E501
        "logger.info(\n"
        '            "plugins(%s), services(%s).",\n'
        '            "updated" if changed_over_p else "unchanged",\n'
        '            "updated" if changed_over_s else "unchanged",\n'
        "        )",
        s,
    )
    write(p, s)


def main():
    fixes = [
        (ROOT / "app" / "api" / "router_auth.py", fix_router_auth),
        (ROOT / "app" / "api" / "router_inference.py", fix_router_inference),
        (ROOT / "app" / "api" / "router_services.py", fix_router_services),
        (ROOT / "app" / "api" / "router_uploads.py", fix_router_uploads),
        (ROOT / "app" / "api" / "router_workflows.py", fix_router_workflows),
        (ROOT / "app" / "services" / "pdf_reader" / "service.py", fix_services_pdf_reader),
        (ROOT / "scripts" / "prefetch_models.py", fix_scripts_prefetch_models),
        (ROOT / "tools" / "build_plugins_index.py", fix_tools_build_plugins_index),
    ]
    for path, fn in fixes:
        if path.exists():
            fn(path)
            print(f"Patched: {path}")
        else:
            print(f"Skip (not found): {path}")

    # Generic B904 (best-effort) across targeted files
    for path in [
        ROOT / "app" / "api" / "router_auth.py",
        ROOT / "app" / "api" / "router_inference.py",
        ROOT / "app" / "api" / "router_uploads.py",
        ROOT / "app" / "services" / "pdf_reader" / "service.py",
    ]:
        if path.exists():
            s = read(path)
            s2 = fix_b904_simple(s)
            if s2 != s:
                write(path, s2)
                print(f"Patched B904 generically: {path}")


if __name__ == "__main__":
    main()
