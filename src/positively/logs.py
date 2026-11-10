"""Session-transcript scanner/rewriter for AI CLI audit logs.

Agents record their own history: Claude Code stores per-project transcripts
under ``~/.claude/projects`` and Codex under ``~/.codex/sessions`` as JSONL.
When a past session contains escalation-flavored prose, the NEXT agent that reads
that history inherits the hesitation. This module scans those transcripts for
negative framing and can rewrite it JSON-safely:

- Only assistant message text fields are rewritten (user prompts, tool
  results, and metadata stay verbatim — facts and human words are preserved).
- Every rewrite goes through the same engine (secret terms, exclusions,
  case preservation, idempotence).
- The original file is archived next to itself as ``<name>.positively.bak``
  before the first rewrite; a JSONL line that fails to parse is preserved
  byte-for-byte.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import engine

# Transcripts modified within this window are considered live (a CLI may be
# appending) and are skipped by --apply unless --force is passed.
FRESH_FILE_SECONDS = 600


def _rewrite_text(text: str) -> tuple[str, int]:
    """Reverse framing in chat text, line by line, keeping inline code
    (backticks) verbatim — same semantics as the markdown apply path."""
    out: list[str] = []
    count = 0
    for line in text.split("\n"):
        new, n = engine._reverse_outside_inline_code(line)
        out.append(new)
        count += n
    return "\n".join(out), count

DEFAULT_CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_CODEX_DIR = Path.home() / ".codex" / "sessions"


@dataclass
class LogFinding:
    path: Path
    line: int
    match: str
    replacement: str


def _assistant_text_fields(obj: object) -> list[str]:
    """Return the assistant-text strings to consider rewriting in one parsed
    JSONL record. Handles Claude Code and Codex session formats."""
    if not isinstance(obj, dict):
        return []
    fields: list[str] = []

    def _content_texts(content: object) -> list[str]:
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for item in content:
                if (
                    isinstance(item, dict)
                    and item.get("type") in ("text", "output_text")
                    and isinstance(item.get("text"), str)
                ):
                    texts.append(item["text"])
        return texts

    # Claude Code: {"type": "assistant", "message": {"content": [...]}}
    if obj.get("type") == "assistant":
        message = obj.get("message")
        if isinstance(message, dict):
            fields.extend(_content_texts(message.get("content")))
        return fields

    # Codex: {"type": "response_item", "payload": {"type": "message",
    #        "role": "assistant", "content": [{"type": "output_text", ...}]}}
    payload = obj.get("payload")
    if obj.get("type") == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            fields.extend(_content_texts(payload.get("content")))
        return fields

    # Codex (older/flat): {"type": "message", "role": "assistant", ...}
    if obj.get("type") == "message" and obj.get("role") == "assistant":
        fields.extend(_content_texts(obj.get("content")))
    return fields


def _rewrite_record(obj: object) -> tuple[object, int]:
    """Rewrite assistant text fields in one parsed record.

    Returns (new_object, match_count). The object is mutated in place where
    practical; returns a new structure for the string-content case.
    """
    if not isinstance(obj, dict):
        return obj, 0
    changes = 0

    def _rewrite_list(content: list) -> None:
        nonlocal changes
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") in ("text", "output_text")
                and isinstance(item.get("text"), str)
            ):
                new, n = _rewrite_text(item["text"])
                if n:
                    item["text"] = new
                    changes += n

    if obj.get("type") == "assistant":
        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                new, n = _rewrite_text(content)
                if n:
                    message["content"] = new
                    changes += n
            elif isinstance(content, list):
                _rewrite_list(content)
        return obj, changes

    payload = obj.get("payload")
    if obj.get("type") == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            content = payload.get("content")
            if isinstance(content, list):
                _rewrite_list(content)
            elif isinstance(content, str):
                new, n = _rewrite_text(content)
                if n:
                    payload["content"] = new
                    changes += n
        return obj, changes

    if obj.get("type") == "message" and obj.get("role") == "assistant":
        content = obj.get("content")
        if isinstance(content, str):
            new, n = _rewrite_text(content)
            if n:
                obj["content"] = new
                changes += n
        elif isinstance(content, list):
            _rewrite_list(content)
    return obj, changes


def project_matches(path_str: str, project_filter: str) -> bool:
    """Match a transcript path against a --project filter.

    Accepts raw substrings, user-style paths (``~/Projects/x``), and the
    munged directory form CLIs use for project storage
    (``-Users-...-Projects-x``).
    """
    if not project_filter:
        return True
    candidates = [project_filter]
    expanded = str(Path(project_filter).expanduser())
    candidates.append(expanded)
    for c in list(candidates):
        candidates.append(c.replace("/", "-"))
    return any(c and c in path_str for c in candidates)


def iter_transcript_files(
    claude_dir: Path | None,
    codex_dir: Path | None,
    project_filter: str = "",
) -> list[Path]:
    """Collect *.jsonl transcript files from the Claude Code and Codex dirs,
    optionally keeping only paths matching ``project_filter``."""
    files: list[Path] = []
    for base in (claude_dir, codex_dir):
        if base is None or not base.is_dir():
            continue
        for p in sorted(base.rglob("*.jsonl")):
            if not project_matches(str(p), project_filter):
                continue
            files.append(p)
    return files


def scan_file(path: Path) -> list[LogFinding]:
    findings: list[LogFinding] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return findings
    for lineno, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for text in _assistant_text_fields(obj):
            for seg_start, _seg_end, seg in _prose_segments(text):
                scan = engine._INLINE_CODE.sub(lambda m: " " * len(m.group(0)), seg)
                for s, e, match, repl, _pat in engine._find_framing_matches(scan, engine.get_config()):
                    findings.append(LogFinding(path, lineno, match, repl))
    return findings


def _prose_segments(text: str):
    """Yield (start, end, segment) for non-inline-code spans of a chat text."""
    pos = 0
    for m in engine._INLINE_CODE.finditer(text):
        if m.start() > pos:
            yield pos, m.start(), text[pos:m.start()]
        pos = m.end()
    if pos < len(text):
        yield pos, len(text), text[pos:]


def rewrite_file(path: Path, *, force: bool = False) -> int:
    """Rewrite assistant text fields in a JSONL transcript. Returns the number
    of substitutions applied (0 when skipped or unchanged).

    Safety: files modified in the last 10 minutes are skipped unless ``force``
    is set — a running CLI may be appending to its transcript, and rewriting
    under it can corrupt the session. The original file is archived as
    ``<name>.positively.bak`` on first change; unparseable lines are preserved
    byte-for-byte.
    """
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not force and (time.time() - path.stat().st_mtime) < FRESH_FILE_SECONDS:
            return 0
    except OSError:
        return 0
    out: list[str] = []
    total = 0
    for line in raw_lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        new_obj, n = _rewrite_record(obj)
        total += n
        out.append(json.dumps(new_obj, ensure_ascii=False))
    if not total:
        return 0
    backup = path.with_suffix(path.suffix + ".positively.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return total


def run(args) -> int:
    from . import config

    cfg = config.load_config()
    engine.set_config(cfg)

    claude_dir = Path(args.claude_dir) if args.claude_dir else DEFAULT_CLAUDE_DIR
    codex_dir = Path(args.codex_dir) if args.codex_dir else DEFAULT_CODEX_DIR
    files = iter_transcript_files(claude_dir, codex_dir, args.project)

    print(f"Scanning {len(files)} transcript file(s) "
          f"(claude: {claude_dir}, codex: {codex_dir})")
    total = 0
    changed_files = 0
    skipped_live = 0
    for path in files:
        findings = scan_file(path)
        if not findings:
            continue
        total += len(findings)
        for f in findings:
            print(f"FRAMING {f.path.name}:{f.line}: '{f.match}' -> '{f.replacement}'")
        if args.apply:
            if not args.force and _is_live(path):
                skipped_live += 1
                continue
            n = rewrite_file(path, force=args.force)
            if n:
                changed_files += 1

    if args.apply:
        summary = (f"\nRewrote {total} finding(s) in {changed_files} file(s); "
                  f"originals archived as *.positively.bak")
        if skipped_live:
            summary += (f"; skipped {skipped_live} live file(s) modified in the last "
                        f"{FRESH_FILE_SECONDS // 60} minutes (close running CLIs or pass "
                        f"--force)")
        print(summary)
    else:
        print(f"\nFound {total} framing finding(s) across {len(files)} file(s). "
              f"Pass --apply to rewrite (assistant text only; originals archived).")
    return 0


def _is_live(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) < FRESH_FILE_SECONDS
    except OSError:
        return False
