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
import subprocess
import sys
from collections import Counter
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


def _drop_preexisting(rep: engine.Report, p: Path, ref: str) -> None:
    """Keep only blockers/cautions the change adds: drop findings the file
    already had at `ref`, matched by (label, text) as a multiset. A file
    absent at `ref` keeps every finding. Framing is whole-file (auto-fixed)."""
    r = subprocess.run(["git", "show", f"{ref}:./{p.name}"], cwd=p.parent or Path("."),
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        return
    base = engine.scan_text(p, r.stdout)
    for attr in ("blockers", "cautions"):
        seen = Counter((f.label, f.match.strip()) for f in getattr(base, attr))
        kept = []
        for f in getattr(rep, attr):
            k = (f.label, f.match.strip())
            if seen[k]:
                seen[k] -= 1
            else:
                kept.append(f)
        setattr(rep, attr, kept)


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

    since = getattr(args, "since", None)
    for p in sorted(paths):
        rep = engine.scan_path(p)
        if not rep:
            continue
        if since:
            _drop_preexisting(rep, p, since)
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
    ap.add_argument("--since", metavar="REF", help="report only blockers/cautions added since git REF")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
