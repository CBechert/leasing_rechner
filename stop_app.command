#!/bin/zsh
cd "$(dirname "$0")"

PORT=8501

# Alle Streamlit-Prozesse auf diesem Port killen
PIDS=$(lsof -Pi :$PORT -sTCP:LISTEN -t 2>/dev/null)

if [ -n "$PIDS" ]; then
  echo "Beende Streamlit auf Port $PORT (PIDs: $PIDS)..."
  kill $PIDS
else
  echo "Kein Streamlit auf Port $PORT gefunden."
fi
