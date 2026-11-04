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
    except ImportError:
        return Config(root=root)

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    cfg = Config(root=root, config_path=config_path)

    # Phrases/words MERGE into the built-in defaults. A config entry with the
    # same negative phrase/word overrides the built-in; entries only in the
    # config extend it.
    if isinstance(data.get("phrases"), dict):
        phrase_map = list(patterns.PHRASE_MAP)
        for neg, pos in data["phrases"].items():
            phrase_map = [(p, r) for p, r in phrase_map if p != neg]
            phrase_map.append((neg, pos))
        cfg.phrase_map = phrase_map
    if isinstance(data.get("words"), dict):
        cfg.word_map = {**patterns.WORD_MAP, **data["words"]}

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
        cfg.blocker_patterns = list(patterns.BLOCKER_PATTERNS) + _parse_blockers(data["blockers"])
    return cfg


def _parse_blockers(raw: list[dict]) -> list[tuple[re.Pattern[str], str, str, str]]:
    out: list[tuple[re.Pattern[str], str, str, str]] = []
    for entry in raw:
        pat = re.compile(entry["pattern"])
        label = entry.get("label", "")
        severity = entry.get("severity", "medium")
        suggestion = entry.get("suggestion", "")
        out.append((pat, label, severity, suggestion))
    return out


class Config:
    """Active configuration — built-ins overlaid with project-local overrides."""

    def __init__(self, root: Path | None = None, config_path: Path | None = None):
        self._root = root or _find_root()
        self._config_path = config_path
        self._phrase_map: list[tuple[str, str]] | None = None
        self._word_map: dict[str, str] | None = None
        self._blocker_patterns: list[tuple[re.Pattern[str], str, str, str]] | None = None
        self._identifier_exclusions: set[str] | None = None
        self._string_exclusions: set[str] | None = None
        self._technical_terms: set[str] | None = None
        self._skip_parts: frozenset[str] | None = None
        self._prose_exts: set[str] | None = None
        self._source_exts: set[str] | None = None

    @property
    def root(self) -> Path:
        return self._root

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def phrase_map(self) -> list[tuple[str, str]]:
        return self._phrase_map if self._phrase_map is not None else patterns.PHRASE_MAP

    @phrase_map.setter
    def phrase_map(self, value: list[tuple[str, str]]) -> None:
        self._phrase_map = value

    @property
    def word_map(self) -> dict[str, str]:
        return self._word_map if self._word_map is not None else patterns.WORD_MAP

    @word_map.setter
    def word_map(self, value: dict[str, str]) -> None:
        self._word_map = value

    @property
    def blocker_patterns(self) -> list[tuple[re.Pattern[str], str, str, str]]:
        return self._blocker_patterns if self._blocker_patterns is not None else patterns.BLOCKER_PATTERNS

    @blocker_patterns.setter
    def blocker_patterns(self, value: list[tuple[re.Pattern[str], str, str, str]]) -> None:
        self._blocker_patterns = value

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