#!/bin/bash
set -euo pipefail

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')

# Only run for commands that contain git push
if ! printf '%s' "$CMD" | grep -q 'git push'; then
    exit 0
fi

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

LINT_OUT=$(make lint 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
    jq -n --arg reason "Lint failed — fix errors before pushing:

$LINT_OUT" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
    exit 1
fi
