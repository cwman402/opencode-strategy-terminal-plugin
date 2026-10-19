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
#
# If the StrategyTerminal app folder has no app-cli.py, the copy bundled in
# ./app-cli/ is installed there too.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
APP_DIR="${ST_CLI_APP_DIR:-$HOME/Apps/StrategyTerminal}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
echo "  app folder    : $APP_DIR"
echo

run mkdir -p "$CONFIG_DIR/plugins" "$CONFIG_DIR/commands" "$CONFIG_DIR/bin"
run cp -f "$HERE/plugins/strategy-terminal.ts" "$CONFIG_DIR/plugins/strategy-terminal.ts"
run cp -f "$HERE/commands/st.md" "$CONFIG_DIR/commands/st.md"
run cp -f "$HERE/bin/st.sh" "$CONFIG_DIR/bin/st.sh"
run chmod +x "$CONFIG_DIR/bin/st.sh"

if [ ! -f "$APP_DIR/app-cli.py" ]; then
  echo "app-cli.py not found in $APP_DIR — installing the bundled copy"
  run mkdir -p "$APP_DIR"
  run cp -f "$HERE/app-cli/app-cli.py" "$APP_DIR/app-cli.py"
  run cp -f "$HERE/app-cli/pdf2png.py" "$APP_DIR/pdf2png.py"
else
  echo "app-cli.py already present in $APP_DIR — left untouched"
fi

cat <<EOF

Installed. Next steps:

  1. Make sure the python used has the app's dependencies
     (streamlit, plotly, yfinance, pandas, kaleido, pymupdf, rich, reportlab).
     Point at it explicitly if needed:
       export ST_CLI_PYTHON="$APP_DIR/venv/bin/python"

  2. Point at the app folder if it is somewhere else:
       export ST_CLI_APP_DIR="$APP_DIR"

  3. Restart OpenCode, then try:
       /st AAPL
       /st VOL TSLA 6mo --show

  API keys are optional and are never stored by this plugin.  Export them in
  your shell if you want the extra sources enabled:
       export FRED_API_KEY=...  FMP_API_KEY=...  POLYGON_API_KEY=...  NEWSAPI_KEY=...
EOF
