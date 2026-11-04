"""Positive-framing check: scan files for negative framing and blocker code.

Exit codes are bit flags:
  0 — clean
  1 — framing violations found
  2 — blockers found
  4 — cautions (destructive intent) found
  Combined: e.g. 3 = framing + blockers, 5 = framing + cautions.

Usage:
  positively check [paths...]
  positively check --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from . import engine
from . import patterns


def _iter_paths(repo: Path, args: argparse.Namespace, cfg: config.Config) -> list[Path]:
    if args.all:
        paths: list[Path] = []
        for p in repo.rglob("*"):
            if not p.is_file():
                continue
            if any(part in cfg.skip_parts for part in p.parts):
                continue
            if p.suffix.lower() in (cfg.prose_exts | cfg.source_exts) or p.name in patterns.FILENAMES:
                paths.append(p)
        return paths
    paths = []
    for a in args.paths:
        p = Path(a)
        if p.is_dir():
            paths.extend(f for f in p.rglob("*") if f.is_file()
                         and (f.suffix.lower() in (cfg.prose_exts | cfg.source_exts)
                              or f.name in patterns.FILENAMES))
        elif p.is_file():
            paths.append(p)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan for negative framing and blockers")
    ap.add_argument("paths", nargs="*", help="files or dirs to scan")
    ap.add_argument("--all", action="store_true", help="scan the whole repo")
    ap.add_argument("--quiet", "-q", action="store_true", help="only print summary")
    args = ap.parse_args()

    cfg = config.load_config()
    engine.set_config(cfg)

    for w in cfg.warnings:
        print(f"WARN config: {w}", file=sys.stderr)

    paths = _iter_paths(cfg.root, args, cfg)
    framing_total = 0
    blocker_total = 0
    caution_total = 0

    for p in sorted(paths):
        rep = engine.scan_path(p)
        if not rep:
            continue
        for v in rep.framing:
            framing_total += 1
            if not args.quiet:
                print(f"FRAMING {p}:{v.line}: '{v.match}' -> '{v.replacement}'")
        for b in rep.blockers:
            blocker_total += 1
            if not args.quiet:
                print(f"BLOCKER[{b.severity}] {p}:{b.line}: {b.label}: {b.match.strip()}")
                print(f"    -> {b.suggestion}")
        for c in rep.cautions:
            caution_total += 1
            if not args.quiet:
                print(f"CAUTION[{c.severity}] {p}:{c.line}: {c.label}: {c.match.strip()}")
                print(f"    -> {c.suggestion}")

    print(f"\nScanned {len(paths)} file(s): {framing_total} framing, {blocker_total} blocker(s), {caution_total} caution(s)")

    rc = 0
    if framing_total:
        rc |= 1
    if blocker_total:
        rc |= 2
    if caution_total:
        rc |= 4
    return rc


if __name__ == "__main__":
    sys.exit(main())