import json
import re
from pathlib import Path

import pandas as pd

from .config import RAW_DIR, DATA_DIR, PROCESSED_DIR


def iter_json_files(subfolder, pattern="*.json"):
    """
    Liefert alle JSON-Dateien aus data/raw/<subfolder>.
    Beispiel: subfolder="carlines" -> data/raw/carlines/*.json
    """
    folder = RAW_DIR / subfolder
    return sorted(folder.glob(pattern))


def read_single_json(path):
    """
    Eine einzelne JSON-Datei einlesen und als Liste von Dicts zurückgeben.

    Behandelte Fälle:
      - [ {...}, {...} ]                 -> Liste
      - { ... }                          -> einzelnes Objekt, wird zur Liste gemacht
      - { "items": [ {...}, {...} ] }    -> nutzt data["items"]
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        return data["items"]

    if isinstance(data, dict):
        return [data]

    return []


def load_raw_data(subfolder):
    """
    Lädt alle JSON-Dateien aus data/raw/<subfolder>
    und gibt einen DataFrame zurück.
    """
    all_records = []

    files = iter_json_files(subfolder)
    if not files:
        print("Keine JSON-Dateien in %s gefunden." % (RAW_DIR / subfolder))
        return pd.DataFrame()

    for file in files:
        try:
            records = read_single_json(file)
            all_records.extend(records)
        except Exception as e:
            print("Fehler beim Lesen von %s: %s" % (file.name, e))

    if not all_records:
        print("Es wurden keine Datensätze aus den JSON-Dateien in %s gelesen." % subfolder)
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    return df


def prettify(slug):
    if not slug:
        return ""
    name = (slug.replace("_", " ")
            .title()
            .replace("Gti", "GTI")
            .replace("Gte", "GTE")
            .replace("Gtd", "GTD")
            .replace("Gtx", "GTX")
            .replace("Id", "ID.")
            .replace("4Motion", "4MOTION")
            .replace("Panamericana", "PanAmericana")
            )
    return name


def split_model_line(filename_stem):
        # Erwartetes Schema: "<modell_slug>__<linie_slug>"
        parts = filename_stem.split("__", 1)
        model_slug = parts[0]
        line_slug = parts[1]
        model = prettify(model_slug)
        line = prettify(line_slug)
        return model, line
    
    
def clean_text(text):
    if not isinstance(text, str):
        return text

    text = text.strip()

    # 1) "Der/Die/Das neue ..." am Anfang entfernen
    text = re.sub(
        r"^\s*(Der|Die|Das)\s+neue[nr]?\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 2) Nackten Artikel am Anfang entfernen: "Der Golf" -> "Golf"
    text = re.sub(
        r"^\s*(Der|Die|Das)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 3) Am Ende eine angehängte Trimline in Anführungszeichen abschneiden
    #    Beispiel: 'Caddy "ENERGY"' -> 'Caddy'
    text = re.sub(
        r'\s+["\'“”][^"\'“”]*["\'“”]\s*$',
        "",
        text,
    )

    # 4) Alle übrigen Anführungszeichen im Text entfernen
    text = re.sub(r'["\'“”]', "", text)

    return text.strip()


def clean_trimline(text):
    if not text or not isinstance(text, str): return text

    # 1) Alle Anführungszeichen raus, egal wo
    text = re.sub(r'["\'“”]', "", text)

    # 2) Mehrfache Leerzeichen normalisieren
    text = re.sub(r"\s+", " ", text).strip()

    # in einen "Slug" umwandeln, dann prettify nutzen
    slug = text.replace(" ", "_")
    return prettify(slug)


def load_carlines():
    df = pd.json_normalize(load_raw_data("carlines")["carlines"].explode())
    df["carlineText"] = df["carlineText"].apply(clean_text)
    df.rename(columns={"carlineText": "model"}, inplace=True)
    df_filtered = df["model"].copy()
    df_filtered.to_csv(f"{PROCESSED_DIR}/carlines.csv", sep=";", index=False)
    return df_filtered


def to_lead_model(name):
    if not isinstance(name, str):
        return name
    for base in LEAD_MODELS_SORTED:
        if base in name:
            return base
    return name


def load_variants():
    df = pd.json_normalize(load_raw_data("variants")["salesbooks"].explode())[["text","trimLines"]].explode("trimLines").reset_index(drop=True)
    df["trimline"] = df["trimLines"].apply(
        lambda x: x.get("trimline") if isinstance(x, dict) else None
    )
    df["text"] = df["text"].apply(clean_text)
    df["trimline"] = df["trimline"].apply(clean_trimline)
    df.rename(columns={"text": "model", "trimline": "line"}, inplace=True)
    df["model"] = df["model"].apply(to_lead_model)
    df["line"].loc[df["line"] == "Pro Mit Infotainment-Paket"] = "Pro"
    df_filtered = df[["model", "line"]].copy()
    df_filtered.to_csv(f"{PROCESSED_DIR}/variants.csv", sep=";", index=False)
    return df_filtered


def get_fuel_from_efficiency_or_text(row):
    eff = row["efficiency.list"]
    if isinstance(eff, dict):
        fuel = eff.get("fuel")
        if fuel and isinstance(fuel, str):
            return fuel.strip().title()
    # Fallback: Text-Spalte analysieren
    text = str(row.get("text", "")).upper()
    if any(kw in text for kw in ["KWH", "ELEKTRO", " EV ", " BEV "]):
        return "Elektro"
    if any(kw in text for kw in ["HYBRID", "PHEV", "PLUG-IN"]):
        return "Hybrid"
    if any(kw in text for kw in ["TDI", "DIESEL", "CDI", "HDI"]):
        return "Diesel"
    if any(kw in text for kw in ["TSI", "TFSI", "BENZIN"]):
        return "Benzin"
    return None


def load_engines():
    all_records = []
    
    for file in iter_json_files("engines"):
        records = read_single_json(file)
        for r in records:
            r = r.copy()
            r["__filename"] = file.stem
            all_records.append(r)
            
    if not all_records:
        return pd.DataFrame()
    
    df_raw = pd.DataFrame(all_records)

    # 2) engines-Liste auf Zeilen bringen
    df_raw = df_raw.explode("engines").reset_index(drop=True)

    # 3) engines-Dict in Spalten auflösen
    df = pd.json_normalize(df_raw["engines"])

    # Dateiname wieder daneben packen
    df["__filename"] = df_raw["__filename"].values

    # 4) Nur relevante Spalten + efficiency.list
    df = df[["text", "power", "gear", "price", "efficiency.list", "__filename"]]

    # 5) efficiency.list explodieren
    df = df.explode("efficiency.list").reset_index(drop=True)
    
    # 6) consumption & fuel aus efficiency.list holen
    df["consumption"] = df["efficiency.list"].apply(
        lambda x: x.get("consumption").replace(",",".") if isinstance(x, dict) else 0.0
    )
    df["fuel"] = df.apply(
    lambda row: (
        row["efficiency.list"].get("fuel").strip().title()
        if isinstance(row["efficiency.list"], dict) and row["efficiency.list"].get("fuel")
        else get_fuel_from_efficiency_or_text(row)
    ),
    axis=1
)

    # 7) Modell & Linie aus Dateinamen extrahieren
    df[["model", "line"]] = df["__filename"].apply(
        lambda s: pd.Series(split_model_line(s))
    )

    # 8) Motor Spalte umbenennen und bereinigen
    df.rename(columns={"text": "engine"}, inplace=True)
    df["engine"] = df["engine"].apply(lambda x: (x.replace(" SCR", "")
                                                 .replace(" OPF", "")
                                                 .replace("Maxi 7-Sitzer  ", "")
                                                 .replace("5-Sitzer  ", "")
                                                 .replace("Der neue Grand California 600  ", "")
                                                 .replace("EURO ", "")
                                                 .replace(" Frontantrieb", "")
                                                 .replace("Der neue Grand California 680  ", ""))
                                      )
    
    # 9) Preis bereinigen
    df["price"] = df["price"].apply(lambda x: x.replace(" €", "")
                                    .replace(".", "")
                                    .replace(",", ".")
                                    )
    
    df_filtered = df[["model", "line", "engine", "power", "gear", "consumption", "fuel", "price"]].copy()
    df_filtered.to_csv(f"{PROCESSED_DIR}/engines.csv", sep=";", index=False)
    return df_filtered


def load_leasing():
    rules_path = RAW_DIR / "leasing" / "leasing.json"
    
    if not rules_path.exists():
        print(f"Leasing-Regeldatei nicht gefunden: {rules_path}")
        return pd.DataFrame()
    
    with rules_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
        
    leasing_cfg = cfg.get("leasing", {})
    
    rows = []

    # Flatten der verschachtelten Struktur
    for fahrzeugart, antriebs_dict in leasing_cfg.items():          # z.B. "PKW", "Nutzfahrzeuge"
        if not isinstance(antriebs_dict, dict):
            continue

        for antrieb, modell_dict in antriebs_dict.items():          # z.B. "Verbrenner", "Elektro/Hybrid"
            if not isinstance(modell_dict, dict):
                continue

            for modell_key, options in modell_dict.items():         # z.B. "Golf", "Tiguan", "Caddy", "Rest"
                if not isinstance(options, list):
                    continue

                bedingung = f"{antrieb}|{modell_key}"

                for opt in options:
                    if not isinstance(opt, dict):
                        continue

                    rows.append({
                        "Leasingoption": opt.get("Leasingoption", ""),
                        "Leasingrate": opt.get("Leasingrate", 0),
                        "Laufzeit": opt.get("Laufzeit", 0),
                        "Freikilometer": opt.get("Freikilometer", 0),
                        "Tankguthaben": opt.get("Tankguthaben", 0),
                        "Bedingung": bedingung,
                    })

    if not rows:
        print("Keine Leasing-Regeln aus JSON generiert.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Typen etwas aufräumen
    df["Leasingrate"] = pd.to_numeric(df["Leasingrate"], errors="coerce").fillna(0.0)
    df["Laufzeit"] = pd.to_numeric(df["Laufzeit"], errors="coerce").fillna(0).astype(int)
    df["Freikilometer"] = pd.to_numeric(df["Freikilometer"], errors="coerce").fillna(0).astype(int)
    df["Tankguthaben"] = pd.to_numeric(df["Tankguthaben"], errors="coerce").fillna(0.0)

    # Mit Semikolon speichern, weil du in der App mit sep=";" einliest
    out_path = PROCESSED_DIR / "leasing.csv"
    df.to_csv(out_path, sep=";", index=False)

    return df


LEAD_MODELS_SORTED = sorted(load_carlines().unique(),key=len,reverse=True)

if __name__ == "__main__":
    
    load_carlines()
    load_variants()
    load_engines()
    load_leasing()