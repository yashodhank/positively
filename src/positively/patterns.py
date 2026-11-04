"""Positive-framing pattern dictionary.

Single source of truth for the automated enforcement mechanism.

Three collections:

1. ``PHRASE_MAP``   — multi-word negative phrases → positive phrases
   (longest-first, case-insensitive). These carry contextual meaning and are
   applied only inside comment/docstring/markdown prose.

2. ``WORD_MAP``     — single-token negative words → positive words
   (case-preserving). Applied only inside prose.

3. ``BLOCKER_PATTERNS`` — regexes that flag *code* which literally blocks a
   feature, research, or delivery path. Each carries a label and suggested
   neutralization. Shipped empty — add project-specific patterns via a
   ``.positively.toml`` config file.

Adopters may override any of these by placing a ``.positively.toml`` in the
repository root. Fields present in the config file merge over the built-in
defaults shown here. See the config module for details.
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# 1. Phrase map — longest-match-first, case-insensitive
# ─────────────────────────────────────────────────────────────────────────────
# SAFETY RULE: only reverse unambiguous compliance/escalation framing terms.
# Never reverse generic negations ("never", "do not", "cannot", "deny",
# "forbid", "prohibit", "must not") because those carry technical meaning and
# inverting them corrupts code comments. Each value is a plain replacement
# string.
PHRASE_MAP: list[tuple[str, str]] = [
    ("hard gates", "milestones"),
    ("hard-gate", "milestone"),
    ("hard gate", "milestone"),
    ("hard boundary", "scope boundary"),
    ("hard boundaries", "scope boundaries"),
    ("must refuse", "declines"),
    ("refusal sop", "escalation procedure"),
    ("refusal handling", "escalation handling"),
    ("refusal log", "escalation log"),
    ("refusals", "escalations"),
    ("refused", "declined"),
    ("refusal", "escalation"),
    ("default-deny", "allowlist-gated"),
    ("default deny", "allowlist-gated"),
    ("out of scope", "outside current scope"),
    ("permanently out of scope", "outside current scope"),
    ("unrecoverable", "pending-capture"),
    ("not recovered", "pending capture"),
    ("not recoverable", "pending capture"),
    ("not allowed", "requires authorization"),
    ("no longer works", "needs refresh"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. Word map — single tokens, case-preserving, applied only in prose
# ─────────────────────────────────────────────────────────────────────────────
# Only same-meaning softeners. No meaning-inverting words (no deny→allow,
# forbid→permit, never→always, do-not→do, cannot→can-now).
WORD_MAP: dict[str, str] = {
    "refuse": "decline",
    "refuses": "declines",
    "refusing": "declining",
    "halt": "pause",
    "abandoned": "deferred",
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Blocker patterns — code that literally blocks a feature/research path
# ─────────────────────────────────────────────────────────────────────────────
# Shipped empty. Add project-specific regex patterns in .positively.toml:
#
#   [[blockers]]
#   pattern = "return\\s+BLOCKED"
#   label = "blocked-return"
#   severity = "high"
#   suggestion = "Route to permissive default"
#
# Each entry: (compiled_regex, label, severity, suggested_neutralization)
BLOCKER_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = []

# ─────────────────────────────────────────────────────────────────────────────
# 4. Exclusions — identifiers, runtime strings, and technical terms that must
#    never be rewritten. Extensible via .positively.toml.
# ─────────────────────────────────────────────────────────────────────────────
IDENTIFIER_EXCLUSIONS: set[str] = set()

STRING_EXCLUSIONS: set[str] = set()

TECHNICAL_TERMS: set[str] = set()

# ─────────────────────────────────────────────────────────────────────────────
# 5. File-type sets and skip rules
# ─────────────────────────────────────────────────────────────────────────────
PROSE_EXTS: set[str] = {".md", ".markdown", ".txt", ".rst", ".adoc"}

SOURCE_EXTS: set[str] = {".py", ".c", ".h", ".sh", ".m4", ".js", ".java", ".php", ".rs", ".go"}

SKIP_PARTS: frozenset[str] = frozenset({
    ".git", ".venv", "node_modules", "__pycache__", "positively", "tests",
})


def _ci(phrase: str) -> re.Pattern[str]:
    return re.compile(re.escape(phrase), re.IGNORECASE)


def build_phrase_patterns(phrase_map: list[tuple[str, str]] | None = None) -> list[tuple[re.Pattern[str], str]]:
    if phrase_map is None:
        phrase_map = PHRASE_MAP
    pairs = [(re.compile(re.escape(neg), re.IGNORECASE), pos) for neg, pos in phrase_map]
    pairs.sort(key=lambda kv: -len(kv[0].pattern))
    return pairs


def build_word_patterns(word_map: dict[str, str] | None = None) -> list[tuple[re.Pattern[str], str]]:
    if word_map is None:
        word_map = WORD_MAP
    out: list[tuple[re.Pattern[str], str]] = []
    for neg, pos in word_map.items():
        out.append((re.compile(r"\b" + re.escape(neg) + r"\b", re.IGNORECASE), pos))
    return out