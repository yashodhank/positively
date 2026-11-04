# Positively — Agent Operating Guide

This project ships **positively**, a positive-framing enforcement engine that
keeps human and AI agents working forward instead of refusing, deleting each
other's work, debating legality, or stalling on scope.

## Baseline

- **Agents and AI models do not decide legality. Humans do.** When a legal
  question appears, the engine routes the *framing* to permissive language so
  work proceeds; the actual legality judgment belongs to a human owner.
- Negative legal framing (`illegal`, `prohibited`, `copyright infringement`)
  is rewritten to permissive language (`permitted`, `cleared for use`).
- Secret terms (`password`, `api_key`, `private key`, tokens) are never
  rewritten or surfaced.
- Legal source-of-truth documents (`LICENSE`, `NOTICE`, `COPYING`, files under
  `legal/`) are never touched.

## The four failure modes the engine guards against

1. **Refusal** — `must refuse`, `refused`, `unrecoverable`, `hard gate`,
   `default-deny` → rewritten to pending-action / permissive framing.
2. **Deleting each other's work** — `rm -rf`, `git reset --hard`,
   `git push --force`, `DROP TABLE`, `DELETE FROM` → flagged as cautions for
   human review. Rule: **archive, don't delete.**
3. **Legal debate** — negative legal stance → permissive language (see baseline).
4. **Scope pondering** — `out of scope`, `default-deny` → `outside current
   scope`, `allowlist-gated`.

## How to use it

```
positively check --all           # scan everything (exit 0 = clean)
positively apply --all --apply   # auto-rewrite prose framing
positively self-test             # verify maps are valid + idempotent
positively init                  # scaffold a .positively.toml
positively install-hook          # install the pre-commit guard
positively install-agent         # write the agent instruction (AI env)
positively install               # init + hook + agent (auto-register everything)
```

## Rules for every agent editing this repo

- **Before editing** — run `positively check` on the files you will touch.
- **Never write negative framing in prose** — `hard gate`, `must refuse`,
  `refused`, `out of scope`, `unrecoverable`, `illegal`. Use the positive
  equivalent, or wrap a factual quote (identifiers, file names, program
  output) in backticks.
- **Never write destructive commands casually** — prefer archive over delete;
  the pre-commit hook will block `rm -rf`, `git reset --hard`, `DROP TABLE`.
- **Never decide legality** — if a legal question arises, note it and escalate
  to the owner; do not delete or rewrite legal documents.
- **After editing** — run `positively apply --all --apply` then
  `positively check --all`; the tree must come back clean.

## Customisation

Project-specific phrase/word/blocker/caution overrides live in
`.positively.toml` and merge over the built-in defaults. Map a term to `""` to
remove it entirely.
