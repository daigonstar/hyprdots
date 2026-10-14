#!/usr/bin/env bash
# Starts the Ollama server in the background if it isn't already running (Super+Ctrl+O).
# Models are chosen and downloaded by ~/.config/hypr/assistant/setup.sh.

if ! command -v ollama >/dev/null 2>&1; then
  notify-send -a Ollama "Ollama is not installed" "Run ~/.config/hypr/assistant/setup.sh to set up the assistant."
  exit 1
fi

if ! pgrep -f "ollama serve" > /dev/null; then
  echo "Starting Ollama server..."
  ollama serve > /dev/null 2>&1 &
  echo "Ollama server started in background."
else
  echo "Ollama server is already running."
fi
