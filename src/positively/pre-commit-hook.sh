#!/usr/bin/env bash
# Positive-framing pre-commit hook.
#
# Auto-reverses negative framing in staged changes and blocks commits that
# introduce blocker code (unless the blocker pattern is explicitly configured).
#
# Install:
#   cp .positively/pre-commit-hook.sh .git/hooks/pre-commit
# Or use the built-in install command:
#   positively install-hook
set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO"

STAGED=()
while IFS= read -r -d '' f; do
  if printf '%s' "$f" | grep -qE '\.(md|markdown|txt|rst|adoc|py|c|h|sh|m4|js|jsx|ts|tsx|java|php|rs|go|swift|kt|rb|css|scss)$' &&
     ! printf '%s' "$f" | grep -qE '^(positively/|tests/)'; then
    STAGED+=("$f")
  fi
done < <(git diff --cached --name-only -z --diff-filter=ACM)

if [ "${#STAGED[@]}" -eq 0 ]; then
  exit 0
fi

# 1. Auto-reverse framing on staged files (idempotent).
python3 -m positively.apply --apply -- "${STAGED[@]}" >/dev/null

# Re-stage anything the engine changed.
for f in "${STAGED[@]}"; do
  if git diff --quiet -- "$f"; then
    :
  else
    git add -- "$f"
  fi
done

# 2. Block commits that contain blocker code.
if python3 -m positively.check --quiet -- "${STAGED[@]}"; then
  exit 0
else
  rc=$?
  echo "positively: blocker or framing issue detected (exit $rc)" >&2
  echo "Run: python3 -m positively.check -- \"${STAGED[*]}\"" >&2
  exit "$rc"
fi