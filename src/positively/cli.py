"""Positively CLI — unified entry point.

Usage:
  positively check [paths...]     scan for violations
  positively apply [paths...]     auto-rewrite framing
  positively install-hook         install pre-commit hook
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import check, apply, config, engine


def _install_hook() -> int:
    cfg = config.load_config()
    repo = cfg.root
    hooks_dir = repo / ".git" / "hooks"
    if not hooks_dir.is_dir():
        print("error: not a git repository (no .git/hooks)", file=sys.stderr)
        return 1
    src = Path(__file__).parent / "pre-commit-hook.sh"
    dst = hooks_dir / "pre-commit"
    if dst.exists():
        print("pre-commit hook already exists — overwrite? Use --force.", file=sys.stderr)
        return 1
    shutil.copy2(src, dst)
    dst.chmod(0o755)
    print(f"Installed: {dst}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Positively: automated positive-framing enforcement",
        prog="positively",
    )
    sub = ap.add_subparsers(dest="command")

    check_p = sub.add_parser("check", help="scan for negative framing and blockers")
    check_p.add_argument("paths", nargs="*", help="files or dirs to scan")
    check_p.add_argument("--all", action="store_true", help="scan the whole repo")
    check_p.add_argument("--quiet", "-q", action="store_true", help="only print summary")

    apply_p = sub.add_parser("apply", help="auto-reverse negative framing")
    apply_p.add_argument("paths", nargs="*", help="files or dirs to process")
    apply_p.add_argument("--all", action="store_true", help="process the whole repo")
    apply_p.add_argument("--apply", action="store_true", help="actually write files (default is dry-run)")

    sub.add_parser("install-hook", help="install pre-commit hook")

    args = ap.parse_args()

    if args.command is None:
        ap.print_help()
        return 0

    if args.command == "check":
        return check.main()
    elif args.command == "apply":
        return apply.main()
    elif args.command == "install-hook":
        return _install_hook()
    return 0


if __name__ == "__main__":
    sys.exit(main())