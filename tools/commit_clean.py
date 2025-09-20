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
    Execute a shell command in the project's root directory.

    Args:
        cmd (list[str]): The shell command to execute.
        check (bool): Whether to raise an error if the command fails.

    Returns:
        subprocess.CompletedProcess: The result of the executed command.
    """
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def run_out(cmd: list[str]) -> str:
    """
    Execute a shell command and return its stdout output.

    Args:
        cmd (list[str]): The shell command to execute.

    Returns:
        str: The stdout output of the command.
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
    Get the name of the current Git branch.

    Returns:
        str: The name of the current branch.
    """
    return run_out(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def local_branch_exists(name: str) -> bool:
    """
    Check if a local Git branch exists.

    Args:
        name (str): Branch name to check.

    Returns:
        bool: True if branch exists locally, False otherwise.
    """
    out = run_out(["git", "branch", "--list", name])
    return bool(out)


def checkout_branch(name: str, create: bool = False) -> None:
    """
    Checkout the specified branch, optionally creating it if it doesn't exist.

    Args:
        name (str): Branch name.
        create (bool): Whether to create the branch if missing.

    Raises:
        SystemExit: If the branch does not exist and creation is not allowed.
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
    Attempt to create a commit with the given message.

    Args:
        message (str): Commit message.

    Returns:
        bool: True if commit succeeds, False otherwise.
    """
    try:
        run(["git", "commit", "-m", message])
        return True
    except subprocess.CalledProcessError:
        return False


def ahead_count(branch: str) -> int:
    """
    Return the number of commits the local branch is ahead of origin/branch.

    Args:
        branch (str): Branch name.

    Returns:
        int: Number of commits ahead, or 0 if not available.
    """
    try:
        out = run_out(["git", "rev-list", "--left-right", "--count", f"origin/{branch}...{branch}"])
        _, ahead = map(int, out.split())
        return ahead
    except Exception:
        return 0


def push_current(remote: str = "origin") -> None:
    """
    Push the current HEAD to the given remote.

    Args:
        remote (str): Name of the remote repository.
    """
    br = current_branch()
    print(f"Pushing current HEAD ({br}) to {remote} ...")
    run(["git", "push", remote, "HEAD"], check=True)
    print("Push done.")


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
    push_only: bool = False,
    only_hooks: bool = False,
) -> int:
    """
    Orchestrate the commit process including optional push and hook runs.

    Returns:
        int: Exit code.
    """
    if not is_git_repo():
        print("Not a Git repository.", file=sys.stderr)
        return 2

    if push_only:
        push_current(remote)
        return 0

    active_branch = current_branch()
    target_branch = branch or active_branch
    if branch and target_branch != active_branch:
        checkout_branch(target_branch, create=create_branch)
        active_branch = target_branch

    if not skip_hooks or only_hooks:
        print("Running pre-commit hooks on all files...")
        run(["pre-commit", "run", "-a"], check=False)

    if only_hooks:
        return 0

    print("Adding all changes to staging...")
    run(["git", "add", "-A"])

    print("Creating commit...")
    committed = try_commit(message)
    if not committed:
        print("Hooks likely modified files during commit. Re-staging and retrying once...")
        run(["git", "add", "-A"])
        committed = try_commit(message)

    if not committed:
        if push and ahead_count(active_branch) > 0:
            print("No new commit created, but branch is ahead. Proceeding to push...")
            push_current(remote)
            return 0
        else:
            print("Commit failed even after retry. Resolve issues and try again.", file=sys.stderr)
            return 1

    if push:
        push_current(remote)
    else:
        print("Skipped push (use --push to enable).")

    return 0


# ------------------------
# Interactive menu
# ------------------------
def menu_pick() -> list[str]:
    """
    Display an interactive menu and return the selected option's arguments.

    Returns:
        list[str]: List of command-line arguments.
    """
    print("\nChoose an operation:")
    print("  1) Commit on current branch + Push")
    print("  2) Switch to branch chore/cleanup then commit + Push")
    print("  3) Create branch chore/cleanup if missing then commit + Push")
    print("  4) Skip pre-commit (quick commit + Push)")
    print("  5) Commit + Push to another remote (asks for name after selection)")
    print("  6) Commit only (no push)")
    print("  7) Run pre-commit only (no commit or push)")
    print("  8) Choose commit type (feat, fix, chore, refactor...) and commit")
    print("  9) Push only (git push origin HEAD)")

    choice = input("Option number: ").strip()

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
    elif choice == "6":
        return ["-m", "chore: local commit"]
    elif choice == "7":
        return ["--only-hooks"]
    elif choice == "8":
        ctype = input("Commit type (e.g., feat, fix, chore, refactor): ").strip()
        msg = input("Commit message: ").strip()
        return ["-m", f"{ctype}: {msg}"]
    elif choice == "9":
        return ["--push-only"]
    else:
        print("Invalid option.")
        sys.exit(1)


# ------------------------
# Entrypoint
# ------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv (list[str] | None): List of arguments or None for sys.argv.

    Returns:
        argparse.Namespace: Parsed arguments.
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
    ap.add_argument("--only-hooks", action="store_true", help="Run pre-commit only, without committing or pushing.")
    ap.add_argument("--push-only", action="store_true", help="Push current HEAD without committing.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point of the script.

    Args:
        argv (list[str] | None): Command-line arguments.

    Returns:
        int: Exit status code.
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
        push_only=bool(args.push_only),
        only_hooks=bool(args.only_hooks),
    )


if __name__ == "__main__":
    raise SystemExit(main())
