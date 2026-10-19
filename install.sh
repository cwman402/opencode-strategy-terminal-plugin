#!/usr/bin/env bash
# Install the Strategy Terminal plugin for OpenCode.
#
#   ./install.sh                 install into ~/.config/opencode
#   ./install.sh --dry-run       show what would happen
#
# It copies:
#   plugins/strategy-terminal.ts -> ~/.config/opencode/plugins/
#   commands/st.md               -> ~/.config/opencode/commands/
#   bin/st.sh                    -> ~/.config/opencode/bin/
#   app-cli/*                    -> ~/.config/opencode/strategy-terminal/
#
# The bundled app-cli/ is a self-contained copy of the StrategyTerminal command
# engine, so no separate StrategyTerminal checkout is required.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
APP_DIR="$CONFIG_DIR/strategy-terminal"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY_RUN" = true ]; then
    echo "would: $*"
  else
    "$@"
  fi
}

echo "Strategy Terminal plugin installer"
echo "  plugin config : $CONFIG_DIR"
echo "  bundled app   : $APP_DIR"
echo

run mkdir -p "$CONFIG_DIR/plugins" "$CONFIG_DIR/commands" "$CONFIG_DIR/bin" "$APP_DIR"
run cp -f "$HERE/plugins/strategy-terminal.ts" "$CONFIG_DIR/plugins/strategy-terminal.ts"
run cp -f "$HERE/commands/st.md" "$CONFIG_DIR/commands/st.md"
run cp -f "$HERE/bin/st.sh" "$CONFIG_DIR/bin/st.sh"
run chmod +x "$CONFIG_DIR/bin/st.sh"
run cp -f "$HERE"/app-cli/*.py "$APP_DIR/"

cat <<EOF

Installed. Next steps:

  1. Make sure the python used has the app's dependencies:
       numpy pandas plotly requests scipy scikit-learn reportlab
       pymupdf kaleido yfinance
     For PNG charts: install kaleido and run 'plotly_get_chrome -y'.
     Point at a specific interpreter if needed:
       export ST_CLI_PYTHON="/path/to/python"

  2. The bundled app is self-contained; no ~/Apps/StrategyTerminal is needed.
     To use a different checkout instead, set:
       export ST_CLI_APP_DIR="/path/to/StrategyTerminal"

  3. Restart OpenCode (or wait for the config watcher to reload), then try:
       /st AAPL
       /st VOL TSLA 6mo --show

  API keys are optional and are never stored by this plugin.  Export them in
  your shell if you want the extra sources enabled:
       export FRED_API_KEY=...  FMP_API_KEY=...  POLYGON_API_KEY=...  NEWSAPI_KEY=...
EOF
