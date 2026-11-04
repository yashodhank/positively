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


# ── file classification ─────────────────────────────────────────────────────

def is_prose(path: Path) -> bool:
    return path.suffix.lower() in get_config().prose_exts


def is_source(path: Path) -> bool:
    return path.suffix.lower() in get_config().source_exts or path.name in patterns.FILENAMES


def should_skip(path: Path, cfg: config.Config | None = None) -> bool:
    """True if a path must never be scanned or rewritten.

    Covers legal source-of-truth documents (SKIP_FILENAMES) and any path part
    in the configured skip set (e.g. `.git`, `.venv`, `node_modules`, `legal`).
    """
    cfg = cfg or get_config()
    if path.name in patterns.SKIP_FILENAMES:
        return True
    return any(part in cfg.skip_parts for part in path.parts)


# ── framing replacement in prose ────────────────────────────────────────────

def _exclusion_spans(text: str, cfg: config.Config) -> list[tuple[int, int]]:
    """Absolute spans of terms that must never be rewritten (identifiers,
    secret/technical terms, quoted string literals). Mirrors ``_mask_exclusions``.
    """
    spans: list[tuple[int, int]] = []
    terms = sorted(cfg.identifier_exclusions | cfg.technical_terms | cfg.secret_terms, key=len, reverse=True)
    for term in terms:
        pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])")
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    for term in sorted(cfg.string_exclusions, key=len, reverse=True):
        pat = re.compile(r"([\"'])" + re.escape(term) + r"(\1)")
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


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


def _case_preserve(repl: str, match: str) -> str:
    if match.isupper():
        return repl.upper()
    if match.istitle():
        return repl.title()
    if match[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _sub_preserve(pat: re.Pattern[str], repl: str, text: str) -> tuple[str, int]:
    def _repl(m: re.Match[str]) -> str:
        return _case_preserve(repl, m.group(0))
    return pat.subn(_repl, text)


def reverse_framing(text: str) -> tuple[str, int]:
    """Apply phrase+word reversal to prose text.

    Returns (new_text, match_count) where match_count is the number of
    individual substitutions applied.
    """
    cfg = get_config()
    total = 0
    text, mask = _mask_exclusions(text, cfg)
    for pat, repl in cfg.compiled_phrases():
        text, n = _sub_preserve(pat, repl, text)
        total += n
    for pat, repl in cfg.compiled_words():
        text, n = _sub_preserve(pat, repl, text)
        total += n
    text = _unmask(text, mask)
    return text, total


def _find_framing_matches(text: str, cfg: config.Config) -> list[tuple[int, int, str, str, str]]:
    """Return (start, end, match, replacement, pattern) for every rewrite the
    engine would apply to ``text``, with the same non-overlap semantics as
    ``reverse_framing`` (longest phrase first, then words; exclusions skipped).
    Positions are absolute character offsets into ``text``.
    """
    excluded = _exclusion_spans(text, cfg)
    consumed = [False] * len(text)
    matches: list[tuple[int, int, str, str, str]] = []

    def _overlaps_excluded(s: int, e: int) -> bool:
        return any(not (e <= xs or s >= xe) for xs, xe in excluded)

    for pat, repl in cfg.compiled_phrases() + cfg.compiled_words():
        for m in pat.finditer(text):
            s, e = m.start(), m.end()
            if any(consumed[s:e]) or _overlaps_excluded(s, e):
                continue
            matches.append((s, e, m.group(0), _case_preserve(repl, m.group(0)), pat.pattern))
            for i in range(s, e):
                consumed[i] = True
    return matches


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
    cfg = get_config()
    for seg_start, seg_end, seg in iter_prose_units(path, text):
        scan = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), seg)
        for s, e, match, repl, pat_str in _find_framing_matches(scan, cfg):
            line = text[: seg_start + s].count("\n") + 1
            violations.append(FramingViolation(
                str(path), line, match, repl, pat_str,
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
    if should_skip(path) or not path.is_file():
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
    """Rewrite framing in place. Returns (new_text, match_count)."""
    if should_skip(path):
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
            new_line, n = _reverse_outside_inline_code(line)
            changes += n
            out.append(new_line)
        else:
            out.append(line)
    return "".join(out), changes


def _reverse_outside_inline_code(line: str) -> tuple[str, int]:
    """Reverse non-inline-code spans of a line; backtick spans stay verbatim.

    Returns (new_line, match_count)."""
    parts: list[str] = []
    pos = 0
    count = 0
    for m in _INLINE_CODE.finditer(line):
        seg, n = reverse_framing(line[pos:m.start()])
        parts += [seg, m.group(0)]
        count += n
        pos = m.end()
    seg, n = reverse_framing(line[pos:])
    parts.append(seg)
    count += n
    return "".join(parts), count


def _apply_source(path: Path, text: str) -> tuple[str, int]:
    changes = 0
    for pat in _comment_patterns(path):
        def repl(m: re.Match[str], _pat=pat) -> str:
            nonlocal changes
            new, n = _reverse_outside_inline_code(m.group(0))
            changes += n
            return new
        text = pat.sub(repl, text)
    return text, changes
