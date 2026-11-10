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


def _is_processable(p: Path, cfg: config.Config) -> bool:
    return p.suffix.lower() in (cfg.prose_exts | cfg.source_exts) or p.name in patterns.FILENAMES


def _iter_paths(repo: Path, args: argparse.Namespace, cfg: config.Config) -> list[Path]:
    paths: list[Path] = []
    if args.all:
        for p in repo.rglob("*"):
            if p.is_file() and not engine.should_skip(p, cfg) and _is_processable(p, cfg):
                paths.append(p)
        return paths
    for a in args.paths:
        p = Path(a)
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and not engine.should_skip(f, cfg) and _is_processable(f, cfg):
                    paths.append(f)
        elif p.is_file():
            paths.append(p)
    return paths


HINT_THRESHOLD = 5000


def _maybe_hint(paths: list[Path]) -> None:
    """Suggest skip config when scanning a very large file set — usually a
    vendored corpus or sample tree that .positively.toml `skip` should cover."""
    if len(paths) > HINT_THRESHOLD:
        print(
            f"HINT: scanning {len(paths)} files. Add heavy directories "
            f"(vendored code, sample corpora, build output) to `skip` in "
            f".positively.toml to make `--all` runs much faster.",
            file=sys.stderr,
        )


def run(args: argparse.Namespace) -> int:
    cfg = config.load_config()
    engine.set_config(cfg)

    for w in cfg.warnings:
        print(f"WARN config: {w}", file=sys.stderr)

    paths = _iter_paths(cfg.root, args, cfg)
    _maybe_hint(paths)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan for negative framing and blockers")
    ap.add_argument("paths", nargs="*", help="files or dirs to scan")
    ap.add_argument("--all", action="store_true", help="scan the whole repo")
    ap.add_argument("--quiet", "-q", action="store_true", help="only print summary")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
