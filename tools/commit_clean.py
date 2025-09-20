#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


# ------------------------
# Shell helpers
# ------------------------
def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """
    Run a shell command and stream stdout/stderr to the console.

    Args:
        cmd (list[str]): Command and arguments to run.
        check (bool, optional): Whether to raise an error on failure. Defaults to True.

    Returns:
        subprocess.CompletedProcess: The completed process object.
    """
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def run_out(cmd: list[str]) -> str:
    """
    Run a shell command and return its trimmed stdout output.

    Args:
        cmd (list[str]): Command and arguments to run.

    Returns:
        str: Trimmed stdout output.
    """
    print(f"$ {' '.join(cmd)}")
    cp = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    return (cp.stdout or "").strip()


# ------------------------
# Git helpers
# ------------------------
def is_git_repo() -> bool:
    """
    Check if the current directory is inside a Git repository.

    Returns:
        bool: True if inside a Git repository, False otherwise.
    """
    try:
        run(["git", "rev-parse", "--is-inside-work-tree"])
        return True
    except subprocess.CalledProcessError:
        return False


def current_branch() -> str:
    """
    Get the current Git branch name.

    Returns:
        str: The current branch name.
    """
    return run_out(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def local_branch_exists(name: str) -> bool:
    """
    Check if a local Git branch exists.

    Args:
        name (str): Branch name.

    Returns:
        bool: True if the branch exists locally, False otherwise.
    """
    out = run_out(["git", "branch", "--list", name])
    return bool(out)


def checkout_branch(name: str, create: bool = False) -> None:
    """
    Checkout to a specified Git branch, optionally creating it.

    Args:
        name (str): Branch name.
        create (bool, optional): Whether to create the branch if it doesn't exist. Defaults to False.

    Raises:
        SystemExit: If the branch doesn't exist and creation is not allowed.
    """
    if local_branch_exists(name):
        run(["git", "checkout", name])
    else:
        if create:
            run(["git", "checkout", "-b", name])
        else:
            raise SystemExit(f"Branch '{name}' not found locally. Use --create-branch to create it.")


def try_commit(message: str) -> bool:
    """
    Attempt to create a Git commit.

    Args:
        message (str): Commit message.

    Returns:
        bool: True if commit was successful, False otherwise.
    """
    try:
        run(["git", "commit", "-m", message])
        return True
    except subprocess.CalledProcessError:
        return False


# ------------------------
# Core logic
# ------------------------
def commit_flow(
    *,
    message: str,
    push: bool,
    remote: str,
    branch: str | None,
    create_branch: bool,
    skip_hooks: bool,
) -> int:
    """
    Handle the full commit process with pre-commit hooks, staging, and pushing.

    Args:
        message (str): Commit message.
        push (bool): Whether to push after committing.
        remote (str): Git remote name.
        branch (str | None): Branch to work on.
        create_branch (bool): Whether to create branch if missing.
        skip_hooks (bool): Whether to skip pre-commit hooks.

    Returns:
        int: Exit status code.
    """
    if not is_git_repo():
        print("Not a Git repository.", file=sys.stderr)
        return 2

    active_branch = current_branch()
    target_branch = branch or active_branch
    if branch and target_branch != active_branch:
        checkout_branch(target_branch, create=create_branch)
        active_branch = target_branch

    if not skip_hooks:
        print("Running pre-commit hooks on all files...")
        run(["pre-commit", "run", "-a"], check=False)

    print("Adding all changes to staging...")
    run(["git", "add", "-A"])

    print("Creating commit...")
    if not try_commit(message):
        print("Hooks likely modified files during commit. Re-staging and retrying once...")
        run(["git", "add", "-A"])
        if not try_commit(message):
            print("Commit failed even after retry. Resolve issues and try again.", file=sys.stderr)
            return 1

    if push:
        print(f"Pushing to {remote}/{active_branch}...")
        run(["git", "push", remote, active_branch])
        print("Push done.")
    else:
        print("Skipped push (use --push to enable).")

    return 0


# ------------------------
# Interactive menu
# ------------------------
def menu_pick() -> list[str]:
    """
    Show an interactive menu and return the selected command-line arguments.

    Returns:
        list[str]: Selected argument list.
    """
    print("\n📋 Choose an operation:")
    print("  1) Commit on current branch + Push")
    print("  2) Switch to branch chore/cleanup then commit + Push")
    print("  3) Create branch chore/cleanup if missing then commit + Push")
    print("  4) Skip pre-commit (quick commit + Push)")
    print("  5) Commit + Push to another remote (asks for name after selection)")

    choice = input("➡️ Option number: ").strip()

    if choice == "1":
        return ["-m", "chore: cleanup commit", "--push"]
    elif choice == "2":
        return ["--branch", "chore/cleanup", "-m", "chore: cleanup commit", "--push"]
    elif choice == "3":
        return ["--branch", "chore/cleanup", "--create-branch", "-m", "chore: cleanup commit", "--push"]
    elif choice == "4":
        return ["-m", "hotfix: quick commit", "--skip-hooks", "--push"]
    elif choice == "5":
        remote = input("Remote name? (e.g., origin, upstream): ").strip() or "origin"
        return ["-m", "chore: cleanup commit", "--push", "--remote", remote]
    else:
        print("❌ Invalid option.")
        sys.exit(1)


# ------------------------
# Entrypoint
# ------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv (list[str] | None, optional): Arguments to parse. Defaults to None.

    Returns:
        argparse.Namespace: Parsed arguments namespace.
    """
    ap = argparse.ArgumentParser(
        description="Run pre-commit, add, commit (with retry if hooks modify files), and optionally push."
    )
    ap.add_argument("-m", "--message", default="chore: cleanup commit", help="Commit message.")
    ap.add_argument("--push", action="store_true", help="Push after committing.")
    ap.add_argument("--remote", default="origin", help="Remote name to push to (default: origin).")
    ap.add_argument("--branch", help="Work on this branch (checkout before committing).")
    ap.add_argument("--create-branch", action="store_true", help="Create branch if it doesn't exist locally.")
    ap.add_argument("--skip-hooks", action="store_true", help="Skip running 'pre-commit run -a' before committing.")
    ap.add_argument("--menu", action="store_true", help="Show an interactive numbered menu.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Main function for script execution.

    Args:
        argv (list[str] | None, optional): Command-line arguments. Defaults to None.

    Returns:
        int: Exit code.
    """
    args = parse_args(argv)

    if args.menu:
        picked = menu_pick()
        args = parse_args(picked)

    return commit_flow(
        message=args.message,
        push=bool(args.push),
        remote=args.remote,
        branch=args.branch,
        create_branch=bool(args.create_branch),
        skip_hooks=bool(args.skip_hooks),
    )


if __name__ == "__main__":
    raise SystemExit(main())

# python tools/commit_clean.py -m "chore: cleanup" --push
# python tools/commit_clean.py --branch chore/cleanup --create-branch -m "chore: cleanup" --push
# python tools/commit_clean.py --remote upstream -m "chore: cleanup" --push
# python tools/commit_clean.py --menu
