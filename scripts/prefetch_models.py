#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dynamic prefetch for all available plugins.

- Discovers plugins via app.plugins.loader
- For each plugin:
    1) Call instance.prefetch() if available
    2) Prefetch models declared in Plugin.REQUIRED_MODELS / required_models()
    3) Prefetch models declared in manifest.json -> "models"
- Supports:
    --only name1,name2    prefetch only specific plugins
    --skip name1,name2    skip these plugins
    --dry-run             list actions without downloading
- Idempotent; keeps a de-dup set to avoid fetching the same model twice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# --- project-local dynamic caches (safe defaults) ---

ROOT = Path(__file__).resolve().parents[1]
HF_HOME_DEFAULT = ROOT / "models_cache" / "huggingface"
TORCH_HOME_DEFAULT = ROOT / "models_cache" / "torch"

# 
os.environ.setdefault("HF_HOME", str(HF_HOME_DEFAULT))
os.environ.setdefault("TORCH_HOME", str(TORCH_HOME_DEFAULT))

#
HF_HOME_DEFAULT.mkdir(parents=True, exist_ok=True)
TORCH_HOME_DEFAULT.mkdir(parents=True, exist_ok=True)

# 
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# Optional: load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Use your real project loader
from app.plugins import loader  # discover(), all_meta(), get()


# ============ utils ============

def info(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def warn(msg: str) -> None:
    print(f"[warn] {msg}")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ============ actual fetchers ============

# Keep a set of (type,id) to avoid duplicates
_PROCESSED: set[tuple[str, str]] = set()


def _snapshot_hf(model_id: str, *, dry: bool = False) -> None:
    """Generic download for HF models: try transformers first, fallback to hub snapshot."""
    if dry:
        print(f"  - would snapshot HF: {model_id}")
        return
    # 1) transformers (lightweight config fetch)
    try:
        from transformers import AutoConfig
        _ = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
        return
    except Exception:
        pass
    # 2) huggingface_hub snapshot (heavier but robust)
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=model_id, local_files_only=False, resume_download=True)
    except Exception as e:
        warn(f"snapshot_download failed for {model_id}: {e}")


def _prefetch_torchvision(name: str, *, dry: bool = False) -> None:
    # Minimal set; extend as needed
    nm = name.lower()
    if nm == "resnet18":
        if dry:
            print("  - would prefetch torchvision resnet18 weights")
            return
        from torchvision.models import ResNet18_Weights, resnet18
        _ = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    else:
        warn(f"unknown torchvision weight: {name}")


def _prefetch_entry(entry: dict[str, Any], *, dry: bool = False) -> None:
    typ = (entry.get("type") or "").strip().lower()
    mid = (entry.get("id") or "").strip()
    if not mid:
        return
    key = (typ, mid)
    if key in _PROCESSED:
        return
    _PROCESSED.add(key)

    if typ in ("hf", "huggingface", "transformers"):
        info(f"Prefetch HF model: {mid}")
        _snapshot_hf(mid, dry=dry)
    elif typ in ("torchvision", "torch_hub"):
        info(f"Prefetch torchvision model: {mid}")
        _prefetch_torchvision(mid, dry=dry)
    else:
        info(f"Skip unknown model type: {entry}")


# ============ manifest helpers ============

def _collect_from_manifest(meta: dict[str, Any]) -> list[dict]:
    """Read models from plugin's manifest.json -> 'models'."""
    path = meta.get("manifest_file")
    out: list[dict] = []
    if not path:
        return out
    p = Path(path)
    if not p.exists():
        return out
    data = _read_json(p)
    models = data.get("models")
    if isinstance(models, list):
        for m in models:
            if isinstance(m, dict) and m.get("id"):
                out.append(m)
    return out


# ============ main logic ============

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dynamic prefetch for all available plugins.")
    ap.add_argument("--only", help="Comma-separated plugin names to include")
    ap.add_argument("--skip", help="Comma-separated plugin names to skip")
    ap.add_argument("--dry-run", action="store_true", help="List actions without downloading")
    args = ap.parse_args(argv)

    only = set((args.only or "").split(",")) - {""}
    skip = set((args.skip or "").split(",")) - {""}
    dry = bool(args.dry_run)

    print("HF_HOME =", os.getenv("HF_HOME"))
    print("TORCH_HOME =", os.getenv("TORCH_HOME"))

    # Discover plugins via the project loader
    loader.discover(reload=True)
    metas = loader.all_meta()  # list of dicts: {"name","folder","manifest_file","plugin_file", ...}

    for meta in metas:
        name = meta.get("name") or meta.get("folder") or "<unknown>"
        folder = meta.get("folder") or name
        if only and name not in only and folder not in only:
            continue
        if name in skip or folder in skip:
            continue

        info(f"Prefetch for plugin: {name}")

        # 1) instance.prefetch() if available
        inst = None
        try:
            inst = loader.get(name)  # may call into plugin; if abstract/invalid, this can raise
            pf = getattr(inst, "prefetch", None)
            if callable(pf):
                if dry:
                    print("  - would call instance.prefetch()")
                else:
                    pf()
        except Exception as e:
            print(f"  ! prefetch() not available or failed for {name}: {e}")

        # 2) REQUIRED_MODELS / required_models()
        if inst:
            # REQUIRED_MODELS as a static list
            try:
                req = list(getattr(inst, "REQUIRED_MODELS", []) or [])
            except Exception:
                req = []
            # required_models() for dynamic declarations
            try:
                fn = getattr(inst, "required_models", None)
                if callable(fn):
                    req += list(fn() or [])
            except Exception:
                pass

            for entry in req:
                _prefetch_entry(entry, dry=dry)

        # 3) Read manifest "models"
        mf_models = _collect_from_manifest(meta)
        for entry in mf_models:
            _prefetch_entry(entry, dry=dry)

    print("\nDone — dynamic prefetch finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
