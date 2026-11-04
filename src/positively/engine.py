"""Shared scan/rewrite engine for positive-framing enforcement."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, patterns

_CFG: config.Config | None = None


def set_config(cfg: config.Config) -> None:
    global _CFG
    _CFG = cfg


def get_config() -> config.Config:
    global _CFG
    if _CFG is None:
        _CFG = config.Config()
    return _CFG


PROSE_EXTS = patterns.PROSE_EXTS
SOURCE_EXTS = patterns.SOURCE_EXTS


@dataclass
class FramingViolation:
    path: str
    line: int
    match: str
    replacement: str
    label: str


@dataclass
class BlockerFinding:
    path: str
    line: int
    match: str
    label: str
    severity: str
    suggestion: str


@dataclass
class Report:
    framing: list[FramingViolation] = field(default_factory=list)
    blockers: list[BlockerFinding] = field(default_factory=list)
    cautions: list[BlockerFinding] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.framing) + len(self.blockers) + len(self.cautions)

    def __bool__(self) -> bool:
        return self.total > 0


def _build_phrases(cfg: config.Config) -> list[tuple[re.Pattern[str], str]]:
    return patterns.build_phrase_patterns(cfg.phrase_map)


def _build_words(cfg: config.Config) -> list[tuple[re.Pattern[str], str]]:
    return patterns.build_word_patterns(cfg.word_map)


# ── framing replacement in prose ────────────────────────────────────────────

def _mask_exclusions(text: str, cfg: config.Config) -> tuple[str, dict[str, str]]:
    """Temporarily mask excluded identifiers/strings/technical terms so they
    are never rewritten. Returns (masked_text, {placeholder: original}).

    - Identifiers and technical terms are masked as bare words.
    - String literals are masked only when quoted, so bare prose words like
      "refused" still reverse to "declined" while the JSON value "refused"
      is preserved.
    """
    mask: dict[str, str] = {}
    terms = sorted(
        cfg.identifier_exclusions | cfg.technical_terms | cfg.secret_terms,
        key=len, reverse=True,
    )
    for i, term in enumerate(terms):
        ph = f"\x00EXCL{i}\x00"
        pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])")
        text, n = pat.subn(ph, text)
        if n:
            mask[ph] = term
    for i, term in enumerate(sorted(cfg.string_exclusions, key=len, reverse=True), start=10000):
        ph = f"\x00EXCL{i}\x00"
        pat = re.compile(r"([\"'])" + re.escape(term) + r"(\1)")
        text, n = pat.subn(lambda m: m.group(1) + ph + m.group(2), text)
        if n:
            mask[ph] = term
    return text, mask


def _unmask(text: str, mask: dict[str, str]) -> str:
    for ph, orig in mask.items():
        text = text.replace(ph, orig)
    return text


def reverse_framing(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Apply phrase+word reversal to prose text. Returns (new_text, changes)."""
    cfg = get_config()
    changes: list[tuple[str, str]] = []
    text, mask = _mask_exclusions(text, cfg)
    for pat, repl in _build_phrases(cfg):
        text, n = pat.subn(repl, text)
        if n:
            changes.append((pat.pattern, repl))
    for pat, repl in _build_words(cfg):
        text, n = pat.subn(repl, text)
        if n:
            changes.append((pat.pattern, repl))
    text = _unmask(text, mask)
    return text, changes


def _case_preserve(repl: str, match: str) -> str:
    if match.isupper():
        return repl.upper()
    if match[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


# ── file classification ─────────────────────────────────────────────────────

def is_prose(path: Path) -> bool:
    return path.suffix.lower() in get_config().prose_exts


def is_source(path: Path) -> bool:
    return path.suffix.lower() in get_config().source_exts or path.name in patterns.FILENAMES


# ── comment extraction (source files) ───────────────────────────────────────
_COMMENT_RE: dict[str, list[re.Pattern[str]]] = {
    ".py": [re.compile(r"#.*$", re.MULTILINE), re.compile(r'"""[\s\S]*?"""'), re.compile(r"'''[\s\S]*?'''")],
    ".sh": [re.compile(r"#.*$", re.MULTILINE)],
    ".m4": [re.compile(r"#.*$", re.MULTILINE), re.compile(r"\bdnl\b.*$", re.MULTILINE)],
    ".c": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".h": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".js": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".java": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".php": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"#.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".rs": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".go": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".ts": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".tsx": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".jsx": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".swift": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".kt": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".rb": [re.compile(r"#.*$", re.MULTILINE)],
    ".css": [re.compile(r"/\*[\s\S]*?\*/")],
    ".scss": [re.compile(r"//.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".yaml": [re.compile(r"#.*$", re.MULTILINE)],
    ".yml": [re.compile(r"#.*$", re.MULTILINE)],
    ".toml": [re.compile(r"#.*$", re.MULTILINE)],
    ".html": [re.compile(r"<!--[\s\S]*?-->")],
    ".htm": [re.compile(r"<!--[\s\S]*?-->")],
    ".sql": [re.compile(r"--.*$", re.MULTILINE), re.compile(r"/\*[\s\S]*?\*/")],
    ".r": [re.compile(r"#.*$", re.MULTILINE)],
    ".lua": [re.compile(r"--.*$", re.MULTILINE), re.compile(r"--\[\[[\s\S]*?\]\]")],
    ".vim": [re.compile(r'^\s*".*$', re.MULTILINE)],
    # extensionless build/config files
    "Makefile": [re.compile(r"#.*$", re.MULTILINE)],
    "Dockerfile": [re.compile(r"#.*$", re.MULTILINE)],
    "Gemfile": [re.compile(r"#.*$", re.MULTILINE)],
    "Justfile": [re.compile(r"#.*$", re.MULTILINE)],
}


def _comment_patterns(path: Path) -> list[re.Pattern[str]]:
    if path.name in _COMMENT_RE:
        return _COMMENT_RE[path.name]
    return _COMMENT_RE.get(path.suffix.lower(), [])


def iter_prose_units(path: Path, text: str):
    """Yield (start_offset, end_offset, segment_text) for rewriteable prose units.

    Offsets are absolute character offsets into ``text`` so line numbers can be
    recovered reliably. For markdown: whole file except fenced code blocks and
    inline code. For source: comment segments and docstrings.
    """
    if is_prose(path):
        yield from _iter_markdown_prose(text)
        return
    if is_source(path):
        yield from _iter_source_comments(path, text)


def _iter_markdown_prose(text: str):
    in_fence = False
    fence_char = ""
    buf: list[str] = []
    start_off = 0
    pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if not in_fence:
                if buf:
                    yield start_off, pos, "".join(buf)
                    buf = []
                in_fence = True
                fence_char = stripped[:3]
            elif stripped[:3] == fence_char:
                in_fence = False
                start_off = pos + len(line)
            pos += len(line)
            continue
        if not in_fence:
            if not buf:
                start_off = pos
            buf.append(line)
        pos += len(line)
    if buf:
        yield start_off, pos, "".join(buf)


def _iter_source_comments(path: Path, text: str):
    for pat in _comment_patterns(path):
        for m in pat.finditer(text):
            seg = m.group(0)
            if seg.strip() in ("", "#", "//", "/*", "*/"):
                continue
            yield m.start(), m.end(), seg


# ── scanning ────────────────────────────────────────────────────────────────

_INLINE_CODE = re.compile(r"(`+).+?\1")


def scan_framing(path: Path, text: str) -> list[FramingViolation]:
    violations: list[FramingViolation] = []
    prose = is_prose(path)
    for seg_start, seg_end, seg in iter_prose_units(path, text):
        scan = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), seg) if prose else seg
        new_seg, changes = reverse_framing(scan)
        if new_seg != scan:
            for pat_str, repl in changes:
                m = re.search(pat_str, scan, re.IGNORECASE)
                if m:
                    line = text[: seg_start + m.start()].count("\n") + 1
                    violations.append(FramingViolation(
                        str(path), line, m.group(0), repl, pat_str,
                    ))
    return violations


def scan_blockers(path: Path, text: str) -> list[BlockerFinding]:
    findings: list[BlockerFinding] = []
    for pat, label, severity, suggestion in get_config().blocker_patterns:
        for m in pat.finditer(text):
            line = text[: m.start()].count("\n") + 1
            findings.append(BlockerFinding(
                str(path), line, m.group(0), label, severity, suggestion,
            ))
    return findings


def scan_cautions(path: Path, text: str) -> list[BlockerFinding]:
    """Flag destructive-intent commands (deletion, force, data loss).

    Scans whole-file text (prose and source) because destructive commands appear
    in shell, SQL, Makefiles, and docs. Detection only — never auto-rewritten.
    """
    findings: list[BlockerFinding] = []
    for pat, label, severity, suggestion in get_config().caution_patterns:
        for m in pat.finditer(text):
            line = text[: m.start()].count("\n") + 1
            findings.append(BlockerFinding(
                str(path), line, m.group(0), label, severity, suggestion,
            ))
    return findings


def scan_path(path: Path) -> Report:
    rep = Report()
    if path.name in patterns.SKIP_FILENAMES or not path.is_file():
        return rep
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rep
    processed = False
    if is_prose(path) or is_source(path):
        rep.framing = scan_framing(path, text)
        processed = True
    if is_source(path):
        rep.blockers = scan_blockers(path, text)
        processed = True
    if processed:
        rep.cautions = scan_cautions(path, text)
    return rep


# ── rewrite ─────────────────────────────────────────────────────────────────

def apply_framing(path: Path, text: str) -> tuple[str, int]:
    """Rewrite framing in place. Returns (new_text, change_count)."""
    if path.name in patterns.SKIP_FILENAMES:
        return text, 0
    if is_prose(path):
        return _apply_markdown(path, text)
    if is_source(path):
        return _apply_source(path, text)
    return text, 0


def _apply_markdown(path: Path, text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    changes = 0
    in_fence = False
    fence_char = ""
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if not in_fence:
                in_fence = True
                fence_char = stripped[:3]
            elif stripped[:3] == fence_char:
                in_fence = False
            out.append(line)
            continue
        if not in_fence:
            new_line = _reverse_outside_inline_code(line)
            if new_line != line:
                changes += 1
            out.append(new_line)
        else:
            out.append(line)
    return "".join(out), changes


def _reverse_outside_inline_code(line: str) -> str:
    """Inline code is verbatim (identifiers, file names, quoted program output): leave it as is."""
    parts, pos = [], 0
    for m in _INLINE_CODE.finditer(line):
        parts += [reverse_framing(line[pos:m.start()])[0], m.group(0)]
        pos = m.end()
    parts.append(reverse_framing(line[pos:])[0])
    return "".join(parts)


def _apply_source(path: Path, text: str) -> tuple[str, int]:
    changes = 0
    for pat in _comment_patterns(path):
        def repl(m: re.Match[str], _pat=pat) -> str:
            nonlocal changes
            new, _ = reverse_framing(m.group(0))
            if new != m.group(0):
                changes += 1
            return new
        text = pat.sub(repl, text)
    return text, changes