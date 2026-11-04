"""Config loader — merges built-in defaults with a project-local .positively.toml.

Place a ``.positively.toml`` in the repository root (or set ``POSITIVELY_CONFIG``
to an explicit path). Fields present in the config override the corresponding
built-in default. Fields absent inherit the built-in value unchanged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import patterns

# Recognised top-level keys. Unknown keys are ignored with a warning so a typo
# (e.g. ``exclusion`` instead of ``exclusions``) does not silently no-op.
KNOWN_KEYS = frozenset({
    "phrases", "words", "exclusions", "string_exclusions", "technical_terms",
    "skip", "prose_exts", "source_exts", "blockers", "cautions",
})

# Written by `positively init`. Kept in sync with the bundled .positively.toml.
DEFAULT_CONFIG_TEMPLATE = """\
# .positively.toml — positive-framing configuration
#
# Copy this file into your repository root and customize it. Every field is
# OPTIONAL and MERGES into the built-in defaults (see README for the defaults).
# Secret terms are NON-OVERRIDABLE and never rewritten.

# ── Exclusions: identifiers / constants never to rewrite ────────────────────
exclusions = [
    # "MY_CONSTANT",
    # "BLOCKED",
]

# ── String literals (JSON/API contract values) never to rewrite ─────────────
string_exclusions = [
    # "halt",
    # "refused",
]

# ── Technical terms where "never"/"cannot" is a fact, not framing ───────────
technical_terms = [
    # "never_type",
    # "cannot parse",
]

# ── Path parts skipped when walking the repo ────────────────────────────────
skip = [".git", ".venv", "node_modules", "__pycache__", "positively", "tests"]

# ── Extra file extensions (merged into built-in sets) ───────────────────────
# prose_exts = [".md", ".markdown", ".txt", ".rst", ".adoc"]
# source_exts = [".py", ".c", ".h", ".sh", ".m4", ".js", ".jsx", ".ts", ".tsx", ".java", ".php", ".rs", ".go", ".swift", ".kt", ".rb", ".css", ".scss", ".yaml", ".yml", ".toml", ".html", ".sql", ".r", ".lua"]

# ── Phrase overrides (negative → positive, case-insensitive, longest-first) ─
# Secret terms cannot be used here (they are ignored + warned).
# Map any term to "" to remove it entirely.
[phrases]
# "hard gates" = "milestones"
# "must refuse" = "declines"
# "refused" = "declined"
# "out of scope" = "outside current scope"
# "unrecoverable" = "pending-capture"
# "not allowed" = "requires authorization"
# "illegal" = "permitted"
# "prohibited" = "permitted"
# "copyright infringement" = "cleared for use"
# "blocked" = ""            # remove a term entirely

# ── Word overrides (single-token softeners, case-preserving) ────────────────
[words]
# refuse = "decline"
# halt = "pause"
# abandoned = "deferred"

# ── Blocker patterns (code that literally blocks a feature path) ────────────
# Detection only; reported by `positively check`.
# [[blockers]]
# pattern = "return\\s+BLOCKED"
# label = "blocked-return"
# severity = "high"
# suggestion = "Route to permissive default"

# ── Caution patterns (destructive intent: deletion / force / data loss) ─────
# Detection only; never auto-rewritten. Extends the built-in caution set.
# [[cautions]]
# pattern = "drop\\s+database"
# label = "drop-database"
# severity = "high"
# suggestion = "Archive, don't drop"
"""


def _find_root() -> Path:
    env = os.environ.get("POSITIVELY_ROOT", "")
    if env:
        return Path(env)
    cwd = Path.cwd()
    for candidate in [cwd] + list(cwd.parents):
        if (candidate / ".positively.toml").exists():
            return candidate
        if (candidate / "positively.toml").exists():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _find_config(root: Path) -> Path | None:
    env = os.environ.get("POSITIVELY_CONFIG", "")
    if env:
        p = Path(env)
        return p if p.is_file() else None
    for name in (".positively.toml", "positively.toml"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def load_config() -> Config:
    root = _find_root()
    config_path = _find_config(root)
    if config_path is None:
        return Config(root=root)

    try:
        import tomllib  # Python ≥3.11
    except ImportError:  # pragma: no cover — requires-python is >=3.11
        return Config(root=root, config_path=config_path)

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError, ValueError) as e:
        cfg = Config(root=root, config_path=config_path)
        cfg.warnings.append(f"could not parse {config_path}: {e}; using defaults")
        return cfg

    if not isinstance(data, dict):
        cfg = Config(root=root, config_path=config_path)
        cfg.warnings.append(f"{config_path}: expected a table of keys, got {type(data).__name__}")
        return cfg

    cfg = Config(root=root, config_path=config_path)

    for key in data:
        if key not in KNOWN_KEYS:
            cfg.warnings.append(f"unknown config key '{key}' (ignored)")

    # Phrases/words MERGE into the built-in defaults. A config entry with the
    # same negative phrase/word (case-insensitively) overrides the built-in.
    if isinstance(data.get("phrases"), dict):
        phrase_map = list(patterns.PHRASE_MAP)
        for neg, pos in data["phrases"].items():
            if not isinstance(pos, str):
                cfg.warnings.append(f"ignored phrase '{neg}': replacement must be a string")
                continue
            if neg.lower() in patterns.SECRET_TERMS or pos.lower() in patterns.SECRET_TERMS:
                cfg.warnings.append(f"ignored phrase '{neg}': secret term may not be rewritten")
                continue
            if neg.lower() == pos.lower():
                cfg.warnings.append(f"ignored phrase '{neg}': maps to itself")
                continue
            phrase_map = [(p, r) for p, r in phrase_map if p.lower() != neg.lower()]
            phrase_map.append((neg, pos))
        cfg.phrase_map = phrase_map
    if isinstance(data.get("words"), dict):
        word_map = dict(patterns.WORD_MAP)
        for neg, pos in data["words"].items():
            if not isinstance(pos, str):
                cfg.warnings.append(f"ignored word '{neg}': replacement must be a string")
                continue
            if neg.lower() in patterns.SECRET_TERMS or pos.lower() in patterns.SECRET_TERMS:
                cfg.warnings.append(f"ignored word '{neg}': secret term may not be rewritten")
                continue
            if neg.lower() == pos.lower():
                cfg.warnings.append(f"ignored word '{neg}': maps to itself")
                continue
            word_map[neg] = pos
        cfg.word_map = word_map

    # Exclusions / skip lists extend the built-in sets.
    if isinstance(data.get("exclusions"), list):
        cfg.identifier_exclusions = set(patterns.IDENTIFIER_EXCLUSIONS) | set(data["exclusions"])
    if isinstance(data.get("string_exclusions"), list):
        cfg.string_exclusions = set(patterns.STRING_EXCLUSIONS) | set(data["string_exclusions"])
    if isinstance(data.get("technical_terms"), list):
        cfg.technical_terms = set(patterns.TECHNICAL_TERMS) | set(data["technical_terms"])
    if isinstance(data.get("skip"), list):
        cfg.skip_parts = frozenset(patterns.SKIP_PARTS) | frozenset(data["skip"])
    if isinstance(data.get("prose_exts"), list):
        cfg.prose_exts = set(patterns.PROSE_EXTS) | set(data["prose_exts"])
    if isinstance(data.get("source_exts"), list):
        cfg.source_exts = set(patterns.SOURCE_EXTS) | set(data["source_exts"])

    if isinstance(data.get("blockers"), list):
        parsed, warns = _parse_patterns(data["blockers"], "blocker")
        cfg.warnings.extend(warns)
        cfg.blocker_patterns = list(patterns.BLOCKER_PATTERNS) + parsed
    if isinstance(data.get("cautions"), list):
        parsed, warns = _parse_patterns(data["cautions"], "caution")
        cfg.warnings.extend(warns)
        cfg.caution_patterns = list(patterns.CAUTION_PATTERNS) + parsed

    # Surface any circular / secret-violation maps introduced by the config.
    cfg.warnings.extend(patterns.validate_maps(cfg.phrase_map, cfg.word_map))
    return cfg


def _parse_patterns(raw: list, kind: str) -> tuple[list[tuple[re.Pattern[str], str, str, str]], list[str]]:
    out: list[tuple[re.Pattern[str], str, str, str]] = []
    warns: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict) or "pattern" not in entry:
            warns.append(f"ignored {kind}: missing 'pattern' key")
            continue
        try:
            pat = re.compile(entry["pattern"])
        except re.error as e:
            warns.append(f"ignored {kind}: invalid regex '{entry['pattern']}': {e}")
            continue
        label = entry.get("label", "")
        severity = entry.get("severity", "medium")
        suggestion = entry.get("suggestion", "")
        out.append((pat, label, severity, suggestion))
    return out, warns


class Config:
    """Active configuration — built-ins overlaid with project-local overrides.

    Compiled phrase/word patterns are cached and invalidated when the
    corresponding map is replaced via its setter.
    """

    def __init__(self, root: Path | None = None, config_path: Path | None = None):
        self._root = root or _find_root()
        self._config_path = config_path
        self._phrase_map: list[tuple[str, str]] | None = None
        self._word_map: dict[str, str] | None = None
        self._blocker_patterns: list[tuple[re.Pattern[str], str, str, str]] | None = None
        self._caution_patterns: list[tuple[re.Pattern[str], str, str, str]] | None = None
        self._identifier_exclusions: set[str] | None = None
        self._string_exclusions: set[str] | None = None
        self._technical_terms: set[str] | None = None
        self._skip_parts: frozenset[str] | None = None
        self._prose_exts: set[str] | None = None
        self._source_exts: set[str] | None = None
        self._compiled_phrases: list[tuple[re.Pattern[str], str]] | None = None
        self._compiled_words: list[tuple[re.Pattern[str], str]] | None = None
        self.warnings: list[str] = []

    # ── roots / identity ────────────────────────────────────────────────────
    @property
    def root(self) -> Path:
        return self._root

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def secret_terms(self) -> frozenset[str]:
        return patterns.SECRET_TERMS

    # ── phrase / word maps (with compiled caching) ──────────────────────────
    @property
    def phrase_map(self) -> list[tuple[str, str]]:
        return self._phrase_map if self._phrase_map is not None else patterns.PHRASE_MAP

    @phrase_map.setter
    def phrase_map(self, value: list[tuple[str, str]]) -> None:
        self._phrase_map = value
        self._compiled_phrases = None

    @property
    def word_map(self) -> dict[str, str]:
        return self._word_map if self._word_map is not None else patterns.WORD_MAP

    @word_map.setter
    def word_map(self, value: dict[str, str]) -> None:
        self._word_map = value
        self._compiled_words = None

    def compiled_phrases(self) -> list[tuple[re.Pattern[str], str]]:
        if self._compiled_phrases is None:
            self._compiled_phrases = patterns.build_phrase_patterns(self.phrase_map)
        return self._compiled_phrases

    def compiled_words(self) -> list[tuple[re.Pattern[str], str]]:
        if self._compiled_words is None:
            self._compiled_words = patterns.build_word_patterns(self.word_map)
        return self._compiled_words

    # ── blocker / caution patterns ──────────────────────────────────────────
    @property
    def blocker_patterns(self) -> list[tuple[re.Pattern[str], str, str, str]]:
        return self._blocker_patterns if self._blocker_patterns is not None else patterns.BLOCKER_PATTERNS

    @blocker_patterns.setter
    def blocker_patterns(self, value: list[tuple[re.Pattern[str], str, str, str]]) -> None:
        self._blocker_patterns = value

    @property
    def caution_patterns(self) -> list[tuple[re.Pattern[str], str, str, str]]:
        return self._caution_patterns if self._caution_patterns is not None else patterns.CAUTION_PATTERNS

    @caution_patterns.setter
    def caution_patterns(self, value: list[tuple[re.Pattern[str], str, str, str]]) -> None:
        self._caution_patterns = value

    # ── exclusions / skip / extensions ──────────────────────────────────────
    @property
    def identifier_exclusions(self) -> set[str]:
        return self._identifier_exclusions if self._identifier_exclusions is not None else patterns.IDENTIFIER_EXCLUSIONS

    @identifier_exclusions.setter
    def identifier_exclusions(self, value: set[str]) -> None:
        self._identifier_exclusions = value

    @property
    def string_exclusions(self) -> set[str]:
        return self._string_exclusions if self._string_exclusions is not None else patterns.STRING_EXCLUSIONS

    @string_exclusions.setter
    def string_exclusions(self, value: set[str]) -> None:
        self._string_exclusions = value

    @property
    def technical_terms(self) -> set[str]:
        return self._technical_terms if self._technical_terms is not None else patterns.TECHNICAL_TERMS

    @technical_terms.setter
    def technical_terms(self, value: set[str]) -> None:
        self._technical_terms = value

    @property
    def skip_parts(self) -> frozenset[str]:
        return self._skip_parts if self._skip_parts is not None else patterns.SKIP_PARTS

    @skip_parts.setter
    def skip_parts(self, value: frozenset[str]) -> None:
        self._skip_parts = value

    @property
    def prose_exts(self) -> set[str]:
        return self._prose_exts if self._prose_exts is not None else patterns.PROSE_EXTS

    @prose_exts.setter
    def prose_exts(self, value: set[str]) -> None:
        self._prose_exts = value

    @property
    def source_exts(self) -> set[str]:
        return self._source_exts if self._source_exts is not None else patterns.SOURCE_EXTS

    @source_exts.setter
    def source_exts(self, value: set[str]) -> None:
        self._source_exts = value
