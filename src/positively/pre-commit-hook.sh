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
while IFS= read -r -d '' f; do
  STAGED+=("$f")
done < <(git diff --cached --name-only -z --diff-filter=ACM)

if [ "${#STAGED[@]}" -eq 0 ]; then
  exit 0
fi

# Auto-reverse framing on staged files (the tool filters type + skip rules).
"${POSITIVELY_RUN[@]}" apply --apply -- "${STAGED[@]}" >/dev/null

# Re-stage anything the engine changed.
for f in "${STAGED[@]}"; do
  if ! git diff --quiet -- "$f"; then
    git add -- "$f"
  fi
done

# Block commits that still contain framing, blockers, or destructive intent.
"${POSITIVELY_RUN[@]}" check --quiet -- "${STAGED[@]}"
