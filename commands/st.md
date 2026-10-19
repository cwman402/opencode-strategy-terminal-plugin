---
description: Run a Strategy Terminal command (e.g. /st AAPL GP 1y, /st WEI --show)
---
Terminal output for the command `$ARGUMENTS`:

!`~/.config/opencode/bin/st.sh "$ARGUMENTS"`

Present the results above to the user as a concise, well-formatted summary:
- lead with the key numbers (price, change, levels, or whatever the command reports)
- keep any tables that were produced
- for every `![...](/path/to/chart.png)` line, show that chart with the `read` tool so it appears inline
- do not invent data that is not in the output; if the command failed, say why
