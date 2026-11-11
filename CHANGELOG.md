# Changelog

## Unreleased

- Pre-commit hook: a partly staged file is checked but no longer rewritten.
  The rewrite was re-added whole and committed the file's unstaged edits.
  Run `positively install-hook --force` to pick up the fixed hook.

## 0.4.0

- New harnesses: Windsurf (`.windsurf/rules/positively.md`) and Cline
  (`.clinerules/positively.md`) — auto-detected, installed, and health-checked
  by `doctor`.
- `positively logs --project` now matches user-style paths (`~/Projects/x`)
  and the munged project-directory form CLIs use (`-Users-...-Projects-x`),
  not just raw substrings.
- `positively install` ends with a pointer to `positively doctor`.
- End-to-end pre-commit hook test (real git repo, PATH-resolved CLI):
  rewrite + re-stage + blocking behavior are exercised, not just file content.

## 0.3.0

- `positively logs` — scan and JSON-safely rewrite AI CLI session transcripts
  (Claude Code `~/.claude/projects`, Codex `~/.codex/sessions`, agy via the
  Claude dir). Assistant text only; originals archived; live transcripts
  (modified < 10 min) skipped unless `--force`.
- `positively reframe` — prompt hygiene: rewrite an ask into positive framing
  before sending it to any CLI (mitigates server-side safety-filter blocks).
- `positively doctor [--fix]` — health check + auto-heal for config, maps,
  hook drift, and stale agent instruction files.
- Pre-commit hook resolves `positively` from PATH first (pipx/uvx/pip all
  work; previously pipx installs silently no-opped).
- Agent instruction hardened: complete legality-gray actions and note them;
  set repo-local git identity instead of stalling on missing identity;
  apply mappings by hand when the CLI is not on PATH.
- Caution scanning: string literals in source code are now scanned
  (`execute("DELETE …")` is caught); docs quoting commands in backticks stay
  clean. `halted` → `paused` added.
- Large-repo hint (>5,000 files) pointing at `skip` config.
- README: troubleshooting table, headless-run flags, CI snippet, legal
  polarity note.

## 0.2.0

- Multi-harness install with auto-discovery: `--agents auto|all|list` writes
  files for Claude Code, Codex (AGENTS.md), Gemini CLI, Cursor, Kilo, and
  the cross-CLI AGENTS.md default.
- `positively new [path]` — fresh-project scaffold.
- `--version`; packaging classifiers; dynamic version; `.pre-commit-hooks.yaml`.
- Marker-delimited memory sections refresh in place (idempotent re-install).

## 0.1.0

- Initial release: check / apply / init / self-test / install-hook /
  install-agent / install. Positive-framing engine, destructive-intent
  cautions, secret terms, legal source-of-truth protection.
