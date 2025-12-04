#!/bin/zsh
cd "$(dirname "$0")"

PORT=8501

# 1. Prüfen: Läuft Streamlit schon auf dem Port?
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
  # Läuft schon → nur Browser öffnen und beenden
  open "http://localhost:$PORT"
  exit 0
fi

# 2. venv anlegen, falls nicht vorhanden
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# 3. venv aktivieren
source .venv/bin/activate

# 4. Dependencies installieren/aktualisieren
pip install -r requirements.txt

# 5. Streamlit im Hintergrund starten (losgelöst vom Terminal)
nohup streamlit run app.py --server.port $PORT > streamlit.log 2>&1 &

# 6. Kurz warten, damit der Server hochkommt
sleep 2

# 7. Browser öffnen
open "http://localhost:$PORT"

# 8. Script endet → Terminal/Automator kann zugehen, Streamlit läuft weiter
exit 0
