#!/usr/bin/env bash
# Shim so the /st command (which calls ~/.config/opencode/bin/st.sh) reaches the
# skill's runner. The real implementation lives in
# skills/strategy-terminal/scripts/st — one copy, no duplication.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in \
  "$HERE/../skills/strategy-terminal/scripts/st" \
  "$HERE/../../skills/strategy-terminal/scripts/st" \
  "$HERE/../strategy-terminal/scripts/st"; do
  if [ -f "$candidate" ]; then
    exec bash "$candidate" "$@"
  fi
done

echo "st: could not find skills/strategy-terminal/scripts/st — reinstall with ./install.sh" >&2
exit 127
