#!/bin/bash
# Splink Test Runner — macOS Launcher
# Double-click this file in Finder to launch the GUI.
# It detaches the app from the terminal, so you can close the Terminal
# window immediately — the GUI keeps running until you quit it (⌘Q / red X).

# Resolve this script's own directory (works regardless of where it's run from)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use the framework Python that has the GUI deps (customtkinter, etc.).
# The default `python3` (pyenv) does NOT have them.
PYTHON="/usr/local/bin/python3"

# Launch detached: nohup + background + disown so it survives the terminal closing.
nohup "$PYTHON" "$DIR/test_runner.py" >/dev/null 2>&1 &
disown

# Give it a moment to start, then close this Terminal window automatically.
sleep 1
osascript -e 'tell application "Terminal" to close (every window whose name contains "SpLink Test Runner")' >/dev/null 2>&1 &
exit 0
