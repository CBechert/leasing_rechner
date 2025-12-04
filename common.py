from pathlib import Path
import json
from slugify import slugify  # falls du python-slugify nutzt

# Basisverzeichnisse
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
JSON_DIR = PROJECT_ROOT / "json_data"   # ggf. anpassen, falls du anders nennst

def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[save_json] geschrieben: {path}")

def slug(s: str) -> str:
    return slugify(s or "", lowercase=False)

def normalize_comma_number(s: str | None) -> str | None:
    if s is None:
        return None
    return s.replace(",", ".")

def clean_engine_text(text: str) -> str:
    """
    Entfernt OPF und SCR aus der Bezeichnung, lässt z.B. 4MOTION stehen.
    """
    tokens = (text or "").split()
    to_strip = {"OPF", "SCR"}
    return " ".join(t for t in tokens if t not in to_strip)