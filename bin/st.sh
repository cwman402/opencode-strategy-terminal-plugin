#!/usr/bin/env bash
# Wrapper for the /st OpenCode command.
#
#   /st AAPL                       -> one-shot command, anonymous
#   /st AAPL --show                -> also render the report, open it in the
#                                     browser and return its pages as images
#   /st AAPL --show --no-open-pdf  -> report + pages, no browser window
#   /st NVDA --user-id 1           -> act as a stored user
#   /st                            -> HELP
#
# Flags (tokens starting with --) are passed to app-cli.py; the remaining words
# form the terminal command.  The /st template hands everything over as one
# string, so the arguments are word-split before flags are classified.
#
# Configuration (optional):
#   ST_CLI_APP_DIR   folder containing app-cli.py
#                    (default: the bundled app at
#                     ~/.config/opencode/strategy-terminal, falling back to
#                     ~/Apps/StrategyTerminal)
#   ST_CLI_PYTHON    python with the app's deps
#                    (default $ST_CLI_PYTHON, else <app>/venv/bin/python,
#                     <app>/.venv/bin/python, ~/venv/bin/python, python3)
set -uo pipefail

if [ -n "${ST_CLI_APP_DIR:-}" ]; then
  APP_DIR="$ST_CLI_APP_DIR"
elif [ -f "${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/strategy-terminal/app-cli.py" ]; then
  APP_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/strategy-terminal"
else
  APP_DIR="$HOME/Apps/StrategyTerminal"
fi

resolve_python() {
  if [ -n "${ST_CLI_PYTHON:-}" ]; then printf '%s' "$ST_CLI_PYTHON"; return; fi
  for candidate in \
    "$APP_DIR/venv/bin/python" \
    "$APP_DIR/.venv/bin/python" \
    "$HOME/venv/bin/python"; do
    [ -x "$candidate" ] && { printf '%s' "$candidate"; return; }
  done
  printf 'python3'
}

PYTHON="$(resolve_python)"

cd "$APP_DIR" 2>/dev/null || {
  echo "app-cli.py folder not found: $APP_DIR (set ST_CLI_APP_DIR)" >&2
  exit 1
}

# Split every incoming argument into words: `st.sh AAPL --show` and
# `st.sh "AAPL --show"` must behave identically.
words=()
for arg in "$@"; do
  read -r -a parts <<< "$arg"
  for word in "${parts[@]:-}"; do
    [ -n "$word" ] && words+=("$word")
  done
done

opts=()
cmd_parts=()
show=false
open_pdf=true
for word in "${words[@]:-}"; do
  case "$word" in
    --show)        show=true ;;
    --open-pdf)    show=true; open_pdf=true ;;
    --no-open-pdf) open_pdf=false ;;
    --*)           opts+=("$word") ;;
    *)             cmd_parts+=("$word") ;;
  esac
done

cmd="${cmd_parts[*]:-HELP}"

# --show: build the report, open it in the browser and rasterise its pages so
# the chat can display them too. --no-open-pdf keeps the PDF on disk only.
if [ "$show" = true ]; then
  opts+=("--pdf")
  if [ "$open_pdf" = true ]; then
    opts+=("--open-pdf")
  else
    opts+=("--no-open-pdf")
  fi
  opts+=("--pdf-png")
fi

exec "$PYTHON" app-cli.py --anonymous --no-save-data "${opts[@]:-}" "$cmd"
