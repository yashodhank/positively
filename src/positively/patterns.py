"""Positive-framing pattern dictionary.

Single source of truth for the automated enforcement mechanism.

Collections:

1. ``PHRASE_MAP``   — multi-word negative phrases → positive phrases
   (longest-first, case-insensitive). Applied only inside prose.

2. ``WORD_MAP``     — single-token negative words → positive words
   (case-preserving). Applied only inside prose. These are *softeners* — they
   reduce escalation/refusal triggers — never meaning inversions.

3. ``BLOCKER_PATTERNS`` — regexes that flag *code* which literally blocks a
   feature, research, or delivery path. Detection only. Shipped empty.

4. ``CAUTION_PATTERNS`` — regexes that flag *destructive intent* (deletion,
   force-push, hard reset, table drops). Detection only; never auto-rewritten.
   Guards the "agents deleting each other's work" failure mode.

5. ``PROTECTED_TERMS`` — legal and secret terms that must **never** be
   rewritten, and which a ``.positively.toml`` config cannot override. Prevents
   the engine from reframing legal signals (illegal → acceptable) or touching
   secrets. The signal must reach a human owner, not be smoothed away.

Adopters may override the phrase/word/blocker/caution maps and the exclusions
by placing a ``.positively.toml`` in the repository root. ``PROTECTED_TERMS``
is fixed.
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# 1. Phrase map — longest-match-first, case-insensitive
# ─────────────────────────────────────────────────────────────────────────────
# SAFETY RULE: only reverse unambiguous compliance/escalation framing terms.
# Never reverse generic negations ("never", "do not", "cannot", "deny",
# "forbid", "prohibit", "must not") because those carry technical meaning and
# inverting them corrupts code comments.
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
# 4. Caution patterns — destructive intent (deletion / force / data loss)
# ─────────────────────────────────────────────────────────────────────────────
# Detection only. These flag commands that can delete another agent's work or
# destroy data, so a human reviews them before they run. Never auto-rewritten.
CAUTION_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (re.compile(r"\brm\s+-rf\b"), "destructive-remove", "high", "Archive, don't delete"),
    (re.compile(r"\brm\s+-r\b"), "recursive-remove", "high", "Archive, don't delete"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "hard-reset", "high", "Prefer git revert"),
    (re.compile(r"\bgit\s+push\s+--force\b"), "force-push", "high", "Prefer --force-with-lease"),
    (re.compile(r"\bgit\s+push\s+-f\b"), "force-push", "high", "Prefer --force-with-lease"),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "force-delete-branch", "high", "Use -d or archive"),
    (re.compile(r"\bDROP\s+TABLE\b"), "drop-table", "high", "Rename/archive instead"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b"), "truncate-table", "high", "Archive, don't truncate"),
    (re.compile(r"\bDELETE\s+FROM\b"), "delete-from", "high", "Archive, don't delete"),
    (re.compile(r"\bwipe\b", re.IGNORECASE), "wipe", "medium", "Archive, don't wipe"),
    (re.compile(r"\bpurge\b", re.IGNORECASE), "purge", "medium", "Archive, don't purge"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 5. Protected terms — legal + secrets that are never rewritten
# ─────────────────────────────────────────────────────────────────────────────
# These are masked before any rewrite and cannot be overridden by config.
# Legal terms must reach a human owner intact; smoothing them away would hide
# a real compliance signal. Secret terms must never be touched or surfaced.
PROTECTED_TERMS: frozenset[str] = frozenset({
    # legal — never reframe; the signal must reach a human owner
    "illegal", "unlawful", "prohibited", "forbidden", "copyright", "trademark",
    "patent", "license", "licence", "eula", "dmca", "infringement", "compliance",
    "regulatory", "gdpr", "hipaa", "litigation", "indemnify", "warranty",
    "liability", "jurisdiction", "statute",
    # secrets — never rewrite, never surface
    "password", "passwd", "credential", "credentials", "secret", "api_key",
    "apikey", "access_key", "secret_key", "private_key", "private key",
    "auth_token", "access_token", "refresh_token",
})

# ─────────────────────────────────────────────────────────────────────────────
# 6. Exclusions — identifiers, runtime strings, and technical terms that must
#    never be rewritten. Extensible via .positively.toml.
# ─────────────────────────────────────────────────────────────────────────────
IDENTIFIER_EXCLUSIONS: set[str] = set()

STRING_EXCLUSIONS: set[str] = set()

TECHNICAL_TERMS: set[str] = set()

# ─────────────────────────────────────────────────────────────────────────────
# 7. File-type sets and skip rules
# ─────────────────────────────────────────────────────────────────────────────
PROSE_EXTS: set[str] = {".md", ".markdown", ".txt", ".rst", ".adoc"}

SOURCE_EXTS: set[str] = {
    ".py", ".c", ".h", ".sh", ".m4", ".js", ".java", ".php", ".rs", ".go",
    ".ts", ".tsx", ".jsx", ".swift", ".kt", ".rb", ".css", ".scss",
    ".yaml", ".yml", ".toml", ".html", ".htm", ".sql", ".r", ".lua", ".vim",
}

# Extensionless files treated as source (comment syntax: `#`).
FILENAMES: frozenset[str] = frozenset({
    "Makefile", "makefile", "GNUmakefile", "Dockerfile", "Containerfile",
    "Gemfile", "Rakefile", "Justfile", "justfile", "Vagrantfile",
})

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


def validate_maps(phrase_map: list[tuple[str, str]], word_map: dict[str, str]) -> list[str]:
    """Return violations that would make the engine contradictory or unsafe.

    Guards against the regression class where an output word re-enters the
    negative set (a circular instruction that stalls downstream agents), and
    against a protected legal/secret term appearing on either side of a map.
    """
    problems: list[str] = []
    negatives: set[str] = set()
    outputs: set[str] = set()

    for neg, pos in phrase_map:
        negatives.add(neg.lower())
        outputs.add(pos.lower())
        if neg.lower() == pos.lower():
            problems.append(f"phrase maps '{neg}' to itself")
    for neg, pos in word_map.items():
        negatives.add(neg.lower())
        outputs.add(pos.lower())
        if neg.lower() == pos.lower():
            problems.append(f"word maps '{neg}' to itself")

    for out in outputs:
        if out in negatives:
            problems.append(f"output '{out}' is also a negative term (circular)")
    for term in PROTECTED_TERMS:
        if term in negatives:
            problems.append(f"protected term '{term}' appears as a negative term")
        if term in outputs:
            problems.append(f"protected term '{term}' appears as an output")
    return problems