"""Positive-framing apply: auto-reverse negative framing in prose.

Every rewrite is logged to positively-audit.md in the project root, with git
author and branch recorded for multi-agent reconciliation. Idempotent:
re-running produces no further changes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import engine
from . import patterns

AUDIT_LOG = "positively-audit.md"

HINT_THRESHOLD = 5000


def _maybe_hint(paths: list[Path]) -> None:
    if len(paths) > HINT_THRESHOLD:
        print(
            f"HINT: processing {len(paths)} files. Add heavy directories "
            f"(vendored code, sample corpora, build output) to `skip` in "
            f".positively.toml to make `--all` runs much faster.",
            file=sys.stderr,
        )


def _git_context(root: Path) -> dict[str, str]:
    """Best-effort git author + branch, never raises."""
    ctx: dict[str, str] = {"author": "", "branch": ""}
    try:
        author = subprocess.run(
            ["git", "config", "user.name"], cwd=root, capture_output=True, text=True, timeout=2,
        )
        ctx["author"] = author.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, timeout=2,
        )
        ctx["branch"] = branch.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ctx


def _log_audit(entries: list[str], log_path: Path | None = None, context: dict[str, str] | None = None) -> bool:
    if not entries:
        return False
    if log_path is None:
        log_path = engine.get_config().root / AUDIT_LOG
    ctx = context or {}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = []
    if ctx.get("author"):
        meta.append(f"author={ctx['author']}")
    if ctx.get("branch"):
        meta.append(f"branch={ctx['branch']}")
    suffix = f" ({', '.join(meta)})" if meta else ""
    with log_path.open("a") as f:
        f.write(f"\n## {ts}{suffix}\n")
        for e in entries:
            f.write(f"- {e}\n")
    return True


def _read(path: Path) -> str:
    # newline="" disables universal-newline translation so CRLF is preserved.
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp file + os.replace so a crash mid-write never corrupts the
    original, and preserve the file's mode."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".positively-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        try:
            st = os.stat(path)
            os.chmod(tmp, st.st_mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _is_processable(p: Path, cfg: config.Config) -> bool:
    return p.suffix.lower() in (cfg.prose_exts | cfg.source_exts) or p.name in patterns.FILENAMES


def run(args: argparse.Namespace) -> int:
    cfg = config.load_config()
    engine.set_config(cfg)
    for w in cfg.warnings:
        print(f"WARN config: {w}", file=sys.stderr)

    repo = cfg.root
    paths: list[Path] = []
    if args.all:
        for p in repo.rglob("*"):
            if p.is_file() and not engine.should_skip(p, cfg) and _is_processable(p, cfg):
                paths.append(p)
    else:
        for a in args.paths:
            p = Path(a)
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file() and not engine.should_skip(f, cfg) and _is_processable(f, cfg):
                        paths.append(f)
            elif p.is_file():
                paths.append(p)
    _maybe_hint(paths)

    total_changes = 0
    audit: list[str] = []
    for p in sorted(paths):
        try:
            text = _read(p)
        except OSError:
            continue
        new_text, n = engine.apply_framing(p, text)
        if n:
            total_changes += n
            audit.append(f"{p}: framing x{n}")
            if args.apply:
                _atomic_write(p, new_text)
            else:
                print(f"[dry-run] would change {p} (framing x{n})")

    if args.apply:
        _log_audit(audit, context=_git_context(repo))
        print(f"\nApplied: {total_changes} change(s) across files. Audit -> {AUDIT_LOG}")
    else:
        print(f"\nDry-run: {total_changes} change(s) across files. Pass --apply to write.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-reverse negative framing")
    ap.add_argument("paths", nargs="*", help="files or dirs to process")
    ap.add_argument("--all", action="store_true", help="process the whole repo")
    ap.add_argument("--apply", action="store_true", help="actually write files (default is dry-run)")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
