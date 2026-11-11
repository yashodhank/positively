#!/usr/bin/env bash
# Positive-framing pre-commit hook.
#
# Auto-reverses negative framing in staged changes and blocks commits that
# introduce framing, blocker code, or destructive-intent cautions.
#
# Install:
#   positively install-hook
#
# Resolves `positively` from PATH first (works for pip, pipx, uvx, and
# venv installs alike); falls back to the module form only when the CLI is
# not on PATH. Exits cleanly when positively is not available at all.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO"

if command -v positively >/dev/null 2>&1; then
  POSITIVELY_RUN=(positively)
elif python3 -c "import positively" >/dev/null 2>&1; then
  POSITIVELY_RUN=(python3 -m positively.cli)
else
  exit 0
fi

STAGED=()
WHOLE=()
while IFS= read -r -d '' f; do
  STAGED+=("$f")
  # apply rewrites the working file and it is re-added whole, which would
  # commit a partly staged file's unstaged edits: such files are only checked.
  if git diff --quiet -- "$f"; then
    WHOLE+=("$f")
  else
    echo "positively: $f is partly staged; not rewritten (stage the whole file to auto-fix)" >&2
  fi
done < <(git diff --cached --name-only -z --diff-filter=ACM)

if [ "${#STAGED[@]}" -eq 0 ]; then
  exit 0
fi

if [ "${#WHOLE[@]}" -gt 0 ]; then
  # Auto-reverse framing on fully staged files (the tool filters type + skip rules).
  "${POSITIVELY_RUN[@]}" apply --apply -- "${WHOLE[@]}" >/dev/null

  # Re-stage anything the engine changed.
  for f in "${WHOLE[@]}"; do
    if ! git diff --quiet -- "$f"; then
      git add -- "$f"
    fi
  done
fi

# Block commits that still contain framing, blockers, or destructive intent.
# Blockers/cautions already in a file at HEAD do not block editing it; only
# ones this commit adds do (no HEAD yet: every finding counts).
SINCE=()
if git rev-parse --verify -q HEAD >/dev/null; then SINCE=(--since HEAD); fi
"${POSITIVELY_RUN[@]}" check --quiet ${SINCE[@]+"${SINCE[@]}"} -- "${STAGED[@]}"
