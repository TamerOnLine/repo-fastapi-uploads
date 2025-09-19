from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
PLUGINS = APP / "plugins"
SERVICES = APP / "services"


def migrate_one(name: str, *, force: bool) -> None:
    src_dir = PLUGINS / name
    src = src_dir / "plugin.py"
    dst_dir = SERVICES / name
    dst = dst_dir / "service.py"

    if not src.exists():
        print(f"[SKIP] {name}: no app/plugins/{name}/plugin.py")
        return

    dst_dir.mkdir(parents=True, exist_ok=True)
    code = src.read_text(encoding="utf-8").replace("class Plugin(", "class Plugin(")
    # إنسخ كما هو (عادة الكلاس اسمه Plugin أصلاً ومتوافق مع AIPlugin)
    dst.write_text(code, encoding="utf-8", newline="\n")
    print(f"[OK] moved plugin → service: {name}")

    if force:
        shutil.rmtree(src_dir, ignore_errors=True)
        print(f"[OK] removed old plugin folder: app/plugins/{name}/")


def discover_plugins() -> list[str]:
    if not PLUGINS.exists():
        return []
    names = []
    for d in PLUGINS.iterdir():
        if d.is_dir() and (d / "plugin.py").exists():
            names.append(d.name)
    return sorted(names)


def main():
    ap = argparse.ArgumentParser(description="Migrate legacy plugins → services")
    ap.add_argument("--only", nargs="*", default=[], help="specific names")
    ap.add_argument("--force", action="store_true", help="delete old plugins/* after migrate")
    args = ap.parse_args()

    names = args.only or discover_plugins()
    if not names:
        print("[INFO] no legacy plugins to migrate.")
        return

    for n in names:
        migrate_one(n, force=args.force)

    print("Migration complete ✅")


if __name__ == "__main__":
    main()
