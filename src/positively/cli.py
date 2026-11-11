"""Positively CLI — unified entry point.

Usage:
  positively check [paths...]     scan for violations
  positively apply [paths...]     auto-rewrite framing
  positively init                 write a .positively.toml template
  positively self-test             validate maps + idempotence
  positively install-hook         install pre-commit hook
  positively install-agent        register agent instructions (AI harnesses)
  positively install               all of the above
  positively new [path]           scaffold a fresh project with everything wired
  positively reframe [text]       rewrite text into positive framing
  positively logs [--apply]       scan/rewrite AI CLI session transcripts
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import agents, apply, check, config, engine, logs, patterns
from . import __version__


def _init(cfg: config.Config) -> int:
    target = cfg.root / ".positively.toml"
    if target.exists():
        print(f"{target} already exists (keeping it)", file=sys.stderr)
        return 0
    target.write_text(config.DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    print(f"Wrote {target}")
    return 0


def _self_test() -> int:
    cfg = config.load_config()
    engine.set_config(cfg)
    problems = patterns.validate_maps(cfg.phrase_map, cfg.word_map)
    sample = " ".join(neg for neg, _ in cfg.phrase_map) + " " + " ".join(cfg.word_map)
    once, _ = engine.reverse_framing(sample)
    twice, _ = engine.reverse_framing(once)
    idempotent = once == twice

    for p in problems:
        print(f"FAIL map: {p}")
    if not idempotent:
        print("FAIL idempotence: applying the map twice changed the output")
    if not problems and idempotent:
        print("OK: maps valid and idempotent")
        return 0
    return 1


def _install_hook(cfg: config.Config, force: bool) -> int:
    hooks_dir = cfg.root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        print("warning: not a git repository (no .git/hooks) — hook not installed", file=sys.stderr)
        return 0
    src = Path(__file__).parent / "pre-commit-hook.sh"
    dst = hooks_dir / "pre-commit"
    if dst.exists() and not force:
        print("pre-commit hook already exists — pass --force to overwrite.", file=sys.stderr)
        return 0
    shutil.copy2(src, dst)
    dst.chmod(0o755)
    print(f"Installed: {dst}")
    return 0


def _run_agents_install(root: Path, spec: str) -> int:
    try:
        targets, detected = agents.resolve(root, spec)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if detected:
        names = ", ".join(sorted(detected))
        print(f"Detected harnesses: {names}")
    else:
        print("No existing harnesses detected")

    changed = agents.install(root, targets)

    if spec == "auto":
        skipped = [n for n in targets if n not in detected and n != "agents"]
        for name in skipped:
            print(f"Skipped {name} (not detected; use --agents {name} or --agents all to add it)")
    if changed:
        for p in changed:
            print(f"Wrote {p}")
        print(f"Agent instructions installed for: {', '.join(sorted(targets))}")
        print("Tip: commit the positively files (AGENTS.md, CLAUDE.md, …) so every agent and CI run gets them.")
    else:
        print(f"Agent instructions already up to date for: {', '.join(sorted(targets))}")
    return 0


def _install_agent(cfg: config.Config, spec: str) -> int:
    return _run_agents_install(cfg.root, spec)


def _install(cfg: config.Config, force: bool, spec: str) -> int:
    _init(cfg)
    _install_hook(cfg, force)
    _run_agents_install(cfg.root, spec)
    print("Verify anytime with: positively doctor")
    return 0


def _reframe(args: argparse.Namespace) -> int:
    """Rewrite arbitrary text (an ask, a handoff note) into positive framing.

    Prompt hygiene: a positively-framed ask is less likely to trip a model's
    own hesitation or a harness's server-side filter, and keeps the receiving
    agent in proceed-mode. Inline code is preserved verbatim.
    """
    cfg = config.load_config()
    engine.set_config(cfg)

    if args.text:
        text = " ".join(args.text)
    elif args.stdin or not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("usage: positively reframe <text>  (or pipe text via stdin)", file=sys.stderr)
        return 1

    out_lines: list[str] = []
    for line in text.split("\n"):
        new, _n = engine._reverse_outside_inline_code(line)
        out_lines.append(new)
    print("\n".join(out_lines), end="" if text.endswith("\n") else "\n")
    return 0


def _new(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        try:
            subprocess.run(["git", "init"], cwd=target, capture_output=True, check=True, timeout=10)
            print(f"Initialized git repository in {target}")
        except (OSError, subprocess.SubprocessError):
            print("warning: could not run `git init` — continuing without it", file=sys.stderr)
    cfg = config.Config(root=target)
    _init(cfg)
    _install_hook(cfg, args.force)
    rc = _run_agents_install(target, args.agents)
    print(f"\nFresh project ready in {target}")
    print("Next: add files, then run `positively check --all` before committing.")
    return rc


def _doctor(args: argparse.Namespace) -> int:
    """One-command health check (+ auto-heal with --fix)."""
    cfg = config.load_config()
    engine.set_config(cfg)
    issues: list[str] = []
    healed: list[str] = []

    cli_path = shutil.which("positively")
    print(f"positively {__version__} · python {sys.version.split()[0]} · root {cfg.root}")
    print(f"config: {cfg.config_path if cfg.config_path else 'none (built-in defaults)'}")
    print(f"cli: {cli_path if cli_path else 'positively not on PATH'}")

    # 1. config warnings
    for w in cfg.warnings:
        issues.append(f"config: {w}")

    # 2. self-test (maps + idempotence)
    problems = patterns.validate_maps(cfg.phrase_map, cfg.word_map)
    sample = " ".join(neg for neg, _ in cfg.phrase_map) + " " + " ".join(cfg.word_map)
    once, _ = engine.reverse_framing(sample)
    twice, _ = engine.reverse_framing(once)
    if problems:
        issues.append(f"self-test: map problems: {'; '.join(problems)}")
    if once != twice:
        issues.append("self-test: map is not idempotent")

    # 3. hook health
    hooks_dir = cfg.root / ".git" / "hooks"
    hook_issues = False
    if hooks_dir.is_dir():
        hook = hooks_dir / "pre-commit"
        bundled = (Path(__file__).parent / "pre-commit-hook.sh").read_text(encoding="utf-8")
        if not hook.exists():
            issues.append("hook: .git/hooks/pre-commit missing")
            hook_issues = True
        elif not os.access(hook, os.X_OK):
            issues.append("hook: .git/hooks/pre-commit not executable")
            hook_issues = True
        elif hook.read_text(encoding="utf-8") != bundled:
            issues.append("hook: content differs from this positively version (stale)")
            hook_issues = True
        if hook_issues and args.fix:
            _install_hook(cfg, force=True)
            healed.append("hook reinstalled")
    else:
        print("hook: not a git repository — skipped")

    # 4. agent files for detected harnesses
    agent_status = agents.status(cfg.root)
    for name, file_issues in sorted(agent_status.items()):
        for fi in file_issues:
            issues.append(f"agents[{name}]: {fi}")
    if agent_status and args.fix:
        targets = set(agent_status)
        agents.install(cfg.root, targets)
        healed.append(f"agent files refreshed for: {', '.join(sorted(targets))}")

    if args.fix and healed:
        print()
        for h in healed:
            print(f"FIXED: {h}")
        # re-verify
        remaining = []
        for w in cfg.warnings:
            remaining.append(f"config: {w}")
        if agents.status(cfg.root):
            for name, file_issues in sorted(agents.status(cfg.root).items()):
                remaining.extend(f"agents[{name}]: {fi}" for fi in file_issues)
        hook = cfg.root / ".git" / "hooks" / "pre-commit"
        bundled = (Path(__file__).parent / "pre-commit-hook.sh").read_text(encoding="utf-8")
        if hooks_dir.is_dir() and (not hook.exists() or hook.read_text(encoding="utf-8") != bundled):
            remaining.append("hook: still not current after fix")
        if problems or once != twice:
            remaining.append("self-test: still failing after fix")
        if remaining:
            print("\nIssues needing manual attention:")
            for r in remaining:
                print(f"  - {r}")
            print("\nRecommendations:")
            print("  - config: edit .positively.toml (see positively init for a template)")
            print("  - self-test: check custom [phrases]/[words] maps for circular entries")
            return 1
        print("\nAll auto-healable issues resolved.")
        return 0

    if issues:
        print()
        for i in issues:
            print(f"ISSUE: {i}")
        print("\nRun `positively doctor --fix` to auto-heal hook and agent-file issues.")
        return 1
    print("\nOK: config, maps, hook, and agent files are healthy and current.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Positively: automated positive-framing enforcement",
        prog="positively",
    )
    ap.add_argument("--version", action="version", version=f"positively {__version__}")
    sub = ap.add_subparsers(dest="command")

    check_p = sub.add_parser("check", help="scan for negative framing and blockers")
    check_p.add_argument("paths", nargs="*", help="files or dirs to scan")
    check_p.add_argument("--all", action="store_true", help="scan the whole repo")
    check_p.add_argument("--quiet", "-q", action="store_true", help="only print summary")
    check_p.add_argument("--since", metavar="REF", help="report only blockers/cautions added since git REF")

    apply_p = sub.add_parser("apply", help="auto-reverse negative framing")
    apply_p.add_argument("paths", nargs="*", help="files or dirs to process")
    apply_p.add_argument("--all", action="store_true", help="process the whole repo")
    apply_p.add_argument("--apply", action="store_true", help="actually write files (default is dry-run)")

    sub.add_parser("init", help="write a .positively.toml template to the current repo")
    sub.add_parser("self-test", help="validate maps + idempotence")

    doctor_p = sub.add_parser("doctor", help="health check: config, hook, agent files")
    doctor_p.add_argument("--fix", action="store_true",
                          help="auto-heal stale/missing hooks and agent files")

    hook_p = sub.add_parser("install-hook", help="install pre-commit hook")
    hook_p.add_argument("--force", action="store_true", help="overwrite an existing hook")

    agent_help = (
        "'auto' (default): write files only for harnesses already in this project, "
        "plus AGENTS.md (Codex CLI, opencode, …); 'all': every known harness; "
        "or a comma list: " + ", ".join(agents.HARNESSES)
    )
    agent_p = sub.add_parser("install-agent", help="register agent instructions (AI harnesses)")
    agent_p.add_argument("--agents", default="auto", help=agent_help)

    install_p = sub.add_parser("install", help="init + install-hook + install-agent")
    install_p.add_argument("--force", action="store_true", help="overwrite existing files")
    install_p.add_argument("--agents", default="auto", help=agent_help)

    new_p = sub.add_parser("new", help="scaffold a fresh project with positively wired in")
    new_p.add_argument("path", nargs="?", default=".", help="directory to create (default: current)")
    new_p.add_argument("--agents", default="all", help="harnesses to wire (default: all)")
    new_p.add_argument("--force", action="store_true", help="overwrite an existing git hook")

    logs_p = sub.add_parser(
        "logs", help="scan/rewrite AI CLI session transcripts (Claude Code, Codex)")
    logs_p.add_argument("--apply", action="store_true",
                        help="rewrite assistant text JSON-safely (originals archived)")
    logs_p.add_argument("--force", action="store_true",
                        help="also rewrite transcripts modified in the last 10 minutes")
    logs_p.add_argument("--project", default="",
                        help="only transcripts whose path contains this substring")
    logs_p.add_argument("--claude-dir", default="", help="override Claude Code projects dir")
    logs_p.add_argument("--codex-dir", default="", help="override Codex sessions dir")

    reframe_p = sub.add_parser(
        "reframe", help="rewrite text into positive framing (prompt hygiene)")
    reframe_p.add_argument("text", nargs="*", help="text to reframe (reads stdin when piped)")
    reframe_p.add_argument("--stdin", action="store_true",
                           help="read text from stdin even when it is a tty")

    args = ap.parse_args()

    if args.command is None:
        ap.print_help()
        return 0
    if args.command == "check":
        return check.run(args)
    if args.command == "apply":
        return apply.run(args)
    if args.command == "init":
        return _init(config.load_config())
    if args.command == "self-test":
        return _self_test()
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "install-hook":
        return _install_hook(config.load_config(), args.force)
    if args.command == "install-agent":
        return _install_agent(config.load_config(), args.agents)
    if args.command == "install":
        return _install(config.load_config(), args.force, args.agents)
    if args.command == "new":
        return _new(args)
    if args.command == "logs":
        return logs.run(args)
    if args.command == "reframe":
        ns = argparse.Namespace(text=args.text, stdin=args.stdin)
        return _reframe(ns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
