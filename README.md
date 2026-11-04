# Positively

**Automated positive-framing enforcement for prose, comments, and docstrings.**

Detects and reverses negative compliance/escalation/blocker language into
positive framing that keeps downstream AI agents, reviewers, and team members
working forward instead of stalling on refusal signals.

## Problem

Negative language — "hard gate", "must refuse", "unrecoverable", "not allowed",
"refused" — causes downstream AI agents to refuse work, conflict, or stall.
This creates gaps, blocks research paths, and wastes context tokens on
correcting framing instead of solving the actual problem.

## Solution

Positively scans prose (markdown, rst, plain text) and source-code comments
(docstrings, inline comments in Python, C, Go, JS, TS, PHP, Rust, Java, Swift,
Kotlin, Ruby, CSS/SCSS, shell) and rewrites negative framing to positive
equivalents — idempotently, case-preserving, with inline-code and code-block
awareness so functional code, identifiers, technical terms, and string
literals are never touched.

## Quick start

```
pip install positively
cd your-project
positively check --all          # scan everything
positively apply --all --apply  # auto-rewrite prose
positively install-hook         # install pre-commit guard
```

Or use the CLI:
```
positively check docs/ src/     # scan specific paths
positively apply README.md      # dry-run one file
positively apply README.md --apply  # rewrite it
```

## Exit codes (`positively check`)

| Code | Meaning |
|------|---------|
| 0    | Clean — no violations |
| 1    | Framing violations found |
| 2    | Blocker code found |
| 3    | Both |

## What it rewrites (built-in defaults)

| Negative phrase | Positive replacement |
|----------------|---------------------|
| hard gates | milestones |
| hard gate | milestone |
| hard boundary | scope boundary |
| must refuse | declines |
| refused | declined |
| refusal / refusals | escalation / escalations |
| default-deny | allowlist-gated |
| out of scope | outside current scope |
| unrecoverable | pending-capture |
| not allowed | requires authorization |
| no longer works | needs refresh |

Single-token meanings: `refuse` → `decline`, `halt` → `pause`, `abandoned` → `deferred`.

## What it skips (never rewritten)

- **Identifiers/constants** in code (configurable via `.positively.toml`)
- **String literals** inside quotes (configurable)
- **Technical terms** where "never"/"cannot" is a fact (configurable)
- **Inline code** in backticks (`identifier`, `output text`)
- **Fenced code blocks** (```` ``` ```` / `~~~`)
- **Generic negations** — "never", "do not", "cannot" are never inverted
- **Safety terms** — `ZipRefused`, path-traversal guards, injection validators are never listed as blockers

## Customisation

Drop a `.positively.toml` at your repository root:

```toml
[phrases]
"must refuse" = "escalates"

[words]
halt = "pause"

exclusions = ["MY_CONSTANT", "SCOPE_GATED", "BLOCKED"]
string_exclusions = ["halt"]

[[blockers]]
pattern = "return\\s+BLOCKED"
label = "blocked-return"
severity = "high"
suggestion = "Route to permissive default"

skip = [".git", ".venv", "out", "dist", "third_party"]
```

See the included [.positively.toml](.positively.toml) for all knobs.

## Pre-commit hook

```
positively install-hook
```

Runs `positively apply --apply` on staged prose/source files and rejects
commits that introduce detectable blocker code. Idempotent — re-running
produces zero changes.

## API

```python
from positively import engine, config

# one-off with defaults
text = "This is a hard gate. It refused."
result, changes = engine.reverse_framing(text)
# result = "This is a milestone. It declined."

# custom config
cfg = config.Config()
cfg.phrase_map = [("hard gate", "milestone")]
engine.set_config(cfg)
```

## Requirements

Python ≥ 3.11. Zero dependencies.

## License

Apache-2.0 — see [LICENSE](LICENSE).