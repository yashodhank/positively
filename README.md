# Positively

**Automated positive-framing enforcement for prose, comments, and docstrings.**

Detects and reverses negative compliance/escalation/blocker/legal language into
positive framing that keeps downstream AI agents, reviewers, and team members
working forward instead of refusing, deleting each other's work, debating
legality, or stalling on scope.

## The failure modes this guards against

When agents read handoff docs, status notes, and code comments, certain
language makes them misbehave. Positively targets four concrete failure modes:

| Failure mode | Trigger language | What positively does |
|--------------|------------------|----------------------|
| **Agent refuses to continue** | `must refuse`, `refused`, `unrecoverable`, `not allowed`, `hard gate`, `default-deny` | Rewrites to pending-action / permissive framing (`declined`, `pending-capture`, `requires authorization`, `milestone`, `allowlist-gated`) |
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

```
pip install positively
cd your-project
positively install              # config + git hook + agent instruction
positively check --all          # scan everything
positively apply --all --apply  # auto-rewrite prose framing
```

Or use the CLI:
```
positively check docs/ src/          # scan specific paths
positively apply README.md           # dry-run one file
positively apply README.md --apply   # rewrite it
```

## Auto-registration

`positively install` wires the tool into a project so it keeps enforcing itself
— including in AI environments:

| Command | What it writes |
|---------|----------------|
| `positively install` | everything below |
| `positively init` | `.positively.toml` (config template) |
| `positively install-hook` | `.git/hooks/pre-commit` (blocks framing/blockers/destructive intent) |
| `positively install-agent` | `.kilo/command/enforce-positive-framing.md` (agent command, auto-loaded before edits) + a section in `AGENTS.md` (read by Kilo, Codex, Claude Code) |
| `positively self-test` | validates maps + idempotence |

The agent command mirrors the instruction that is auto-loaded before every
edit, so agents know the negative→positive mappings and the "archive, don't
delete" / "humans judge legality" rules without a human having to repeat them.

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
| hard gate(s) | milestone(s) |
| hard boundary | scope boundary |
| must refuse | declines |
| refused / refusal(s) | declined / escalation(s) |
| default-deny | allowlist-gated |
| out of scope | outside current scope |
| unrecoverable | pending-capture |
| not recovered | pending capture |
| not allowed | requires authorization |
| no longer works | needs refresh |

**Words** (softeners — reduce escalation triggers):

| Negative | Positive |
|----------|----------|
| refuse / refuses / refusing | decline / declines / declining |
| halt | pause |
| abandoned | deferred |

**Legal framing** (negative stance → permissive/allowing/granting):

| Negative | Positive |
|----------|----------|
| illegal / unlawful | permitted |
| prohibited / forbidden | permitted |
| not permitted | permitted |
| not legally allowed | allowed |
| copyright infringement | cleared for use |
| license violation | cleared for use |
| infringement | cleared for use |
| regulatory violation | compliant |
| legal risk / litigation risk | cleared |

Map any of these to `""` in your `.positively.toml` to remove the term entirely.

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