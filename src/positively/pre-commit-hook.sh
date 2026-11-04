#!/usr/bin/env bash
# Positive-framing pre-commit hook.
#
# Auto-reverses negative framing in staged changes and blocks commits that
# introduce framing, blocker code, or destructive-intent cautions.
#
# Install:
#   positively install-hook
# or:
#   cp src/positively/pre-commit-hook.sh .git/hooks/pre-commit
#
# The hook delegates file-type and skip decisions to the tool itself, so the
# supported extension set and skip rules stay in one place (no duplicated list).
set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO"

# Skip silently if positively is not installed on the default python3.
if ! python3 -c "import positively" >/dev/null 2>&1; then
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
python3 -m positively.apply --apply -- "${STAGED[@]}" >/dev/null

# Re-stage anything the engine changed.
for f in "${STAGED[@]}"; do
  if ! git diff --quiet -- "$f"; then
    git add -- "$f"
  fi
done

# Block commits that still contain framing, blockers, or destructive intent.
python3 -m positively.check --quiet -- "${STAGED[@]}"
