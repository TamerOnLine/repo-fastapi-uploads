#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """شغل أمر وأطبع النتيجة للـ stdout مباشرة"""
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run pre-commit, add, commit, and optionally push.")
    parser.add_argument(
        "-m", "--message", default="chore: cleanup commit", help="رسالة الـ commit (افتراضي: 'chore: cleanup commit')."
    )
    parser.add_argument("--push", action="store_true", help="لو حابب تعمل push للـ origin/HEAD بعد الـ commit.")
    args = parser.parse_args(argv)

    try:
        print("🚀 Running pre-commit hooks...")
        run(["pre-commit", "run", "-a"], check=False)

        print("➕ Adding all changes to staging...")
        run(["git", "add", "-A"])

        print("📝 Creating commit...")
        run(["git", "commit", "-m", args.message])

        if args.push:
            print("🌐 Pushing to origin...")
            run(["git", "push", "origin", "HEAD"])
            print("✅ Push done.")
        else:
            print("ℹ️ Skipped push (use --push to enable).")

        return 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return e.returncode


if __name__ == "__main__":
    sys.exit(main())
