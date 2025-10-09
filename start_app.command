#!/bin/zsh
cd "$(dirname "$0")"

# Falls das venv noch nicht existiert → neu anlegen
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# Aktivieren
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt

# App starten
exec streamlit run app.py
