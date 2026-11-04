"""Positive-framing apply: auto-reverse negative framing in prose.

Every rewrite is logged to positively-audit.md in the project root.
Idempotent: re-running produces no further changes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import engine
from . import patterns

AUDIT_LOG = "positively-audit.md"


def _log_audit(entries: list[str], log_path: Path | None = None) -> bool:
    if not entries:
        return False
    if log_path is None:
        log_path = engine.get_config().root / AUDIT_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a") as f:
        f.write(f"\n## {ts}\n")
        for e in entries:
            f.write(f"- {e}\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-reverse negative framing")
    ap.add_argument("paths", nargs="*", help="files or dirs to process")
    ap.add_argument("--all", action="store_true", help="process the whole repo")
    ap.add_argument("--apply", action="store_true", help="actually write files (default is dry-run)")
    args = ap.parse_args()

    cfg = config.load_config()
    engine.set_config(cfg)

    repo = cfg.root
    paths: list[Path] = []
    if args.all:
        for p in repo.rglob("*"):
            if not p.is_file():
                continue
            if any(part in cfg.skip_parts for part in p.parts):
                continue
            if p.name in patterns.SKIP_FILENAMES:
                continue
            if p.suffix.lower() in (cfg.prose_exts | cfg.source_exts) or p.name in patterns.FILENAMES:
                paths.append(p)
    else:
        for a in args.paths:
            p = Path(a)
            if p.is_dir():
                paths.extend(f for f in p.rglob("*") if f.is_file())
            elif p.is_file():
                paths.append(p)

    total_changes = 0
    audit: list[str] = []
    for p in sorted(paths):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        new_text, n = engine.apply_framing(p, text)
        if n:
            total_changes += n
            audit.append(f"{p}: framing x{n}")
            if args.apply:
                p.write_text(new_text, encoding="utf-8")
            else:
                print(f"[dry-run] would change {p} (framing x{n})")

    if args.apply:
        _log_audit(audit)
        print(f"\nApplied: {total_changes} change(s) across files. Audit -> {AUDIT_LOG}")
    else:
        print(f"\nDry-run: {total_changes} change(s) across files. Pass --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())