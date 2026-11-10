# Positively

**Automated positive-framing enforcement for prose, comments, and docstrings.**

Detects and reverses negative compliance/escalation/blocker/legal language into
positive framing that keeps downstream AI agents, reviewers, and team members
working forward instead of `refusing`, deleting each other's work, debating
legality, or stalling on scope.

## The failure modes this guards against

When agents read handoff docs, status notes, and code comments, certain
language makes them misbehave. Positively targets four concrete failure modes:

| Failure mode | Trigger language | What positively does |
|--------------|------------------|----------------------|
| **Agent stops mid-task** | `must refuse`, `refused`, `unrecoverable`, `not allowed`, `hard gate`, `default-deny` | Rewrites to pending-action / permissive framing (`declined`, `pending-capture`, `requires authorization`, `milestone`, `allowlist-gated`) |
| **Agents delete each other's work** | `rm -rf`, `git reset --hard`, `DROP TABLE`, `DELETE FROM`, `git push --force` | **Caution detection** — flags destructive commands for human review, never auto-rewrites |
| **Legal/illegality debates** | `illegal`, `prohibited`, `copyright infringement`, `license violation` | Reframes to permissive language (`permitted`, `cleared for use`, `allowed`) so work proceeds |
| **Counterproductive scope pondering** | `out of scope`, `default-deny`, `permanently out of scope` | Reframes to `outside current scope`, `allowlist-gated` so the next agent proceeds |

**Baseline:** agents and AI models do not decide legality — humans do. The
engine rewrites negative legal *framing* so agents stop rejecting work; it does
not change the underlying legal reality, which humans judge.

The engine is **idempotent, case-preserving, and aware of inline code, fenced
code blocks, string literals, and identifiers** so it never corrupts functional
code or meaning.

## Quick start

Install (the package is not yet on PyPI — install straight from git):

```
pipx install git+https://github.com/yashodhank/positively.git
# or: pip install git+https://github.com/yashodhank/positively.git
# or run without installing: uvx --from git+https://github.com/yashodhank/positively.git positively --help
```

### Existing project

```
cd your-project
positively install              # config + git hook + agent instructions
positively check --all          # scan everything
positively apply --all --apply  # auto-rewrite prose framing
```

`positively install` **auto-detects** which AI coding CLIs the project already
uses (Claude Code, Gemini CLI, Cursor, Kilo, opencode, Codex CLI…) and wires
positive-framing instructions into exactly those. Use `--agents all` to write
every harness, or `--agents claude,gemini` to pick explicitly.

### Fresh project

```
positively new my-project        # git init + config + hook + all agent files
cd my-project
```

One command produces a working setup every harness can read from the start.

### Scan / rewrite directly

```
positively check docs/ src/          # scan specific paths
positively apply README.md           # dry-run one file
positively apply README.md --apply   # rewrite it
```

## `positively doctor` — health check + auto-heal

```
positively doctor          # check config, maps, hook, agent files
positively doctor --fix    # auto-heal stale/missing hooks and agent files
```

Detects: config parse errors and unknown keys, invalid/circular maps,
missing or non-executable pre-commit hook, **hook content drift** (written by
an older positively version), and **stale agent instruction files** after a
positively upgrade. `--fix` re-runs the install writers for everything it can
heal and re-verifies; anything manual (a broken `.positively.toml`) comes
back with the exact repair hint.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Hook never fires on commit | `positively` installed via pipx/uvx; older hooks probed `python3 -c "import positively"` which fails for isolated installs | `positively install-hook --force` (v0.3.0+ hooks resolve the CLI from PATH) |
| Agent instruction files mention old rules | Project wired by an older positively version | `positively doctor --fix` |
| `positively check --all` slow on a huge repo | Vendored corpus / sample tree not in `skip` | Add heavy directories to `skip` in `.positively.toml` (a hint prints automatically past 5,000 files) |
| `positively logs --apply` skipped files | Transcript modified in the last 10 minutes (live session) | Close the running CLI or pass `--force` |
| Legal-fact doc got polarity-inverted | Standalone `forbidden`/`illegal` rewrite to `permitted` in prose | Quote the term in backticks, or map it to `""` in `.positively.toml` |
| agy task blocked before the model ran | Gemini server-side safety filter on the request | Reframe the ask: `positively reframe "<ask>"` |
| Agent says it cannot run `positively check` | positively not on the agent's PATH (project venv install) | Install globally: `pipx install git+https://github.com/yashodhank/positively.git` — hooks and agents both resolve it from PATH |

## Supported AI harnesses

`positively install-agent` writes the files each harness auto-loads. One
instruction text drives all of them, so behavior stays consistent:

| `--agents` name | Harness | Files written |
|----------------|---------|---------------|
| `agents` (alias: `codex`, `opencode`) | Codex CLI, opencode, Kilo, Amp, Goose, … | section in `AGENTS.md` |
| `claude` (alias: `claude-code`) | Claude Code | section in `CLAUDE.md` + `.claude/commands/positively.md` |
| `gemini` (alias: `gemini-cli`) | Gemini CLI | section in `GEMINI.md` |
| `cursor` | Cursor | `.cursor/rules/positively.mdc` |
| `kilo` | Kilo | `.kilo/command/enforce-positive-framing.md` |
| `windsurf` | Windsurf | `.windsurf/rules/positively.md` |
| `cline` | Cline | `.clinerules/positively.md` |

- **`auto` (default):** detect what the project already uses and write only
  that — plus `AGENTS.md`, the cross-CLI default every coding agent reads.
- **`all`:** write every harness (used by `positively new`).
- Marker-delimited sections are refreshed in place on re-install, so
  upgrading the instruction text never duplicates content.

## Prompt hygiene (`positively reframe`)

Rewrite an ask (or any text) into positive framing before sending it to an AI
CLI. A permissively-framed ask is less likely to trip a model's own
hesitation or a harness's server-side safety filter, and keeps the receiving
agent in proceed-mode:

```
positively reframe "This is illegal, the model must refuse" 
# → "This is permitted, the model declines"

echo "The task is out of scope and unrecoverable" | positively reframe
```

Uses the same maps and backtick/inline-code preservation as the engine;
project `.positively.toml` overrides apply.

## Session-transcript rewrites (`positively logs`)

Agents record their own history: Claude Code stores per-project transcripts in
`~/.claude/projects`, Codex in `~/.codex/sessions` (JSONL). When a past
session contains escalation-flavored prose, the next agent that reads that
history inherits the hesitation. `positively logs` scans and JSON-safely
rewrites those transcripts:

```
positively logs                          # scan all Claude Code + Codex transcripts
positively logs --project icrecover      # only transcripts for one project
positively logs --project icrecover --apply   # rewrite assistant text in place
```

- Only **assistant message text** is rewritten; user prompts, tool results,
  and metadata stay verbatim.
- Inline code (backticks) inside transcript text is preserved.
- Every changed file is archived next to itself as `*.positively.bak`.
- Lines that fail to parse are preserved byte-for-byte.
- Transcripts modified in the last 10 minutes are treated as **live** (a CLI
  may still be appending) and are skipped — close the running CLI or pass
  `--force`.

## Running agents headlessly (tested flags)

| CLI | Non-interactive invocation |
|-----|----------------------------|
| Claude Code | `claude -p "ASK" --dangerously-skip-permissions` |
| Codex | `codex exec --sandbox danger-full-access "ASK"` |
| agy | `agy -p "ASK" --dangerously-skip-permissions --print-timeout 1500s` |

agy's `--mode auto` may be unavailable on some accounts; its output is
buffered until the run finishes. Note that server-side safety filters
(e.g. Gemini's, behind agy) can block a request before the model reads any
instruction file — keep the ask itself in positive framing (this is what
`positively`'s language conventions are for).

## Auto-registration

`positively install` wires the tool into a project so it keeps enforcing itself
— including in AI environments:

| Command | What it writes |
|---------|----------------|
| `positively install` | everything below (auto-detected harnesses) |
| `positively init` | `.positively.toml` (config template) |
| `positively install-hook` | `.git/hooks/pre-commit` (blocks framing/blockers/destructive intent) |
| `positively install-agent` | agent instructions for detected harnesses (see table above) |
| `positively new [path]` | fresh-project scaffold: git + config + hook + all harness files |
| `positively logs [--apply]` | scan/rewrite AI CLI session transcripts (Claude Code, Codex) |
| `positively reframe <text>` | rewrite an ask into positive framing before sending it to a CLI |
| `positively self-test` | validates maps + idempotence |

The agent instruction tells every model to **keep work moving forward**: proceed
by default, record open questions for the owner, humans judge legality,
archive instead of delete — with the negative→positive mappings spelled out so
agents never write escalation-inducing language in the first place.

## Exit codes (`positively check`)

Bit flags — combine them:

| Code | Meaning |
|------|---------|
| 0 | Clean |
| 1 | Framing violations found |
| 2 | Blocker code found |
| 4 | Cautions (destructive intent) found |

`3` = framing + blockers, `5` = framing + cautions, `7` = all three.

## What it rewrites (built-in defaults)

**Phrases** (negative → positive):

| Negative | Positive |
|----------|----------|
| `hard gate(s)` | milestone(s) |
| `hard boundary` | scope boundary |
| `must refuse` | declines |
| `refused` / `refusal(s)` | declined / escalation(s) |
| `default-deny` | allowlist-gated |
| `out of scope` | outside current scope |
| `unrecoverable` | pending-capture |
| `not recovered` | pending capture |
| `not allowed` | requires authorization |
| `no longer works` | needs refresh |

**Words** (softeners — reduce escalation triggers):

| Negative | Positive |
|----------|----------|
| `refuse` / `refuses` / `refusing` | decline / declines / declining |
| `halt` | pause |
| `abandoned` | deferred |

**Legal framing** (negative stance → permissive/allowing/granting):

| Negative | Positive |
|----------|----------|
| `illegal` / `unlawful` | permitted |
| `prohibited` / `forbidden` | permitted |
| `not permitted` | permitted |
| `not legally allowed` | allowed |
| `copyright infringement` | cleared for use |
| `license violation` | cleared for use |
| `infringement` | cleared for use |
| `regulatory violation` | compliant |
| `legal risk` / `litigation risk` | cleared |

Map any of these to `""` in your `.positively.toml` to remove the term entirely.

**Polarity note:** the standalone legal words (`illegal`, `prohibited`,
`forbidden`) rewrite to `permitted` — correct when the prose carries an
*attitude* ("this feels permitted, let's avoid it") and deliberately
permissive. But in a document that states a **legal fact** ("the EULA
forbids X"), the rewrite inverts the meaning. For such documents, keep the
terms verbatim by quoting them in backticks, or map them to `""` in your
`.positively.toml`. Legal source-of-truth files (`LICENSE`, `NOTICE`,
`legal/`) are always skipped.

## What it never rewrites

- **Secret terms** — `password`, `credential`, `secret`, `api_key`,
  `private key`, tokens. Non-overridable.
- **Legal source-of-truth documents** — `LICENSE`, `NOTICE`, `COPYING`,
  `COPYRIGHT`, `AUTHORS`, `PATENTS`, and files under a `legal/` directory.
  These stay verbatim so humans have an intact reference for judging legality.
- **Identifiers/constants**, **string literals**, **technical terms** — configurable.
- **Inline code** (backticks) and **fenced code blocks** — always verbatim.
- **Generic negations** — `never`, `do not`, `cannot` are never inverted.
- **Security protections** — path-traversal guards, injection validators,
  `ZipRefused`-style defenses are never listed as blockers.

## Destructive-intent cautions

`positively check` flags commands that can delete another agent's work or
destroy data, so a human reviews them before they run:

- `rm -rf`, `rm -r`
- `git reset --hard`, `git push --force`, `git branch -D`
- `DROP TABLE`, `TRUNCATE TABLE`, `DELETE FROM`
- `wipe`, `purge`

These are **detected, never auto-rewritten**. The companion rule for agents:
*archive, don't delete*.

## Customisation

Drop a `.positively.toml` at your repository root:

```toml
[phrases]
"must refuse" = "escalates"
"illegal" = "permitted"       # override the default
"blocked" = ""                # remove a term entirely

[words]
halt = "pause"

exclusions = ["MY_CONSTANT", "BLOCKED"]

[[blockers]]
pattern = "return\\s+BLOCKED"
label = "blocked-return"
severity = "high"
suggestion = "Route to permissive default"

[[cautions]]
pattern = "drop\\s+database"
label = "drop-database"
severity = "high"
suggestion = "Archive, don't drop"
```

All maps merge over the built-in defaults. Attempts to rewrite a secret term are
rejected with a warning. See the included [.positively.toml](.positively.toml).

## Supported file types

- **Prose:** Markdown, RST, AsciiDoc, plain text.
- **Source comments:** Python, C/C++, Go, Rust, JavaScript/TypeScript/JSX, Java,
  PHP, Ruby, Swift, Kotlin, Shell, CSS/SCSS, YAML, TOML, HTML, SQL, R, Lua, Vim.
- **Extensionless:** `Makefile`, `Dockerfile`, `Gemfile`, `Justfile`, and similar.

## Pre-commit hook

```
positively install-hook
```

Runs `positively apply --apply` on staged prose/source files, then rejects
commits that introduce framing, blocker code, or destructive-intent cautions.
The hook delegates file-type and skip decisions to the tool itself (no
duplicated extension list), and exits cleanly if `positively` is not installed.

### pre-commit framework

If your project uses the [pre-commit](https://pre-commit.com) framework:

```yaml
repos:
  - repo: https://github.com/yashodhank/positively
    rev: v0.3.0
    hooks:
      - id: positively-apply   # auto-reverse framing on staged files
      - id: positively-check   # flag framing/destructive-intent commits
```

### CI (GitHub Actions)

```yaml
# .github/workflows/positively.yml
name: positively
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install git+https://github.com/yashodhank/positively.git
      - run: positively check --all
```

## API

```python
from positively import engine, config

cfg = config.Config()
cfg.phrase_map = [("hard gate", "milestone")]
engine.set_config(cfg)

text = "This is a hard gate."
result, changes = engine.reverse_framing(text)
# result = "This is a milestone."

# Validate a custom map for contradictions / secret-term violations
from positively import patterns
problems = patterns.validate_maps(cfg.phrase_map, cfg.word_map)
```

## Requirements

Python ≥ 3.11. Zero dependencies.

## License

Apache-2.0 — see [LICENSE](LICENSE).