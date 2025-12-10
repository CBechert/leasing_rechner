import json
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from src.config import PROCESSED_DIR, STATIONS_PATH

# ---------------------------------------------------------------------
# Page setup (muss vor dem ersten Streamlit-Output stehen)
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Leasing Rechner",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://creativecommons.tankerkoenig.de/json"
API_KEY = st.secrets["tankerkoenig"]["api_key"]

# Globale Spritpreis-Tabelle, wird im Hauptteil befüllt
spritpreise: dict[str, float] = {}


# =====================================================================
# Hilfsfunktionen & Daten-Logik
# =====================================================================

def find_leasing_bedingung(
    leasing_df: pd.DataFrame,
    kategorie: str,
    modell: str,
) -> tuple[str, str]:
    """
    Ermittelt eine passende Leasingbedingung (Kraftstoff + Modell-Regel).

    Reihenfolge:
      1) Exakte Regel (Kategorie + Modell)
      2) Fallback "Rest" für die Kategorie
      3) Rückfall auf ursprüngliche Kombination
    """
    mask_exact = (
        (leasing_df["Bedingung Kraftstoff"] == kategorie)
        & (leasing_df["Bedingung Modell"] == modell)
    )
    if mask_exact.any():
        return kategorie, modell

    mask_rest = (
        (leasing_df["Bedingung Kraftstoff"] == kategorie)
        & (leasing_df["Bedingung Modell"] == "Rest")
    )
    if mask_rest.any():
        return kategorie, "Rest"

    return kategorie, modell


@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Lädt Autos- und Leasing-Daten aus dem processed-Verzeichnis
    und bereinigt numerische Spalten.
    """
    autos_path = PROCESSED_DIR / "autos.csv"
    leasing_path = PROCESSED_DIR / "leasing.csv"

    autos = pd.read_csv(autos_path, sep=";")
    leasing = pd.read_csv(leasing_path, sep=";")

    # Verbrauchsspalten numerisch
    for col in ("l/100km", "kWh/100km"):
        if col in autos.columns:
            autos[col] = pd.to_numeric(autos[col], errors="coerce").fillna(0.0)

    # Leasingrate + Laufzeit numerisch
    for col, default in (("Leasingrate", 0.0), ("Laufzeit", 0)):
        if col in leasing.columns:
            leasing[col] = pd.to_numeric(leasing[col], errors="coerce").fillna(default)

    return autos, leasing


@st.cache_data
def load_stations() -> list[dict]:
    """
    Lädt eine lokale Stationsliste aus STATIONS_PATH.
    """
    with STATIONS_PATH.open("r", encoding="utf-8") as f:
        stations = json.load(f)
    return stations


def auto_selectbox_single(
    label: str,
    options,
    key: str,
    placeholder: str | None = None,
):
    """
    Selectbox-Helfer mit Sonderfall für Kraftstoff und Auto-Select bei genau einer Option.

    Verhalten:
      - label == "Kraftstoff":
          immer automatisch eine gültige Auswahl (erste Option) erzwingen
      - 0 Optionen:
          leere Selectbox mit Placeholder
      - 1 Option:
          diese Option wird im Session-State gesetzt
      - >= 2 Optionen:
          Selectbox startet leer mit Placeholder
    """
    options = list(options) if options is not None else []

    # Spezieller Ablauf für Kraftstoff
    if label == "Kraftstoff":
        current = st.session_state.get(key)
        if current not in options and options:
            st.session_state[key] = options[0]
        return st.selectbox(label, options, key=key)

    # 0 Optionen
    if not options:
        return st.selectbox(
            label,
            [],
            index=None,
            placeholder=placeholder,
            key=key,
        )

    # 1 Option
    if len(options) == 1:
        current = st.session_state.get(key)
        if current not in options:
            st.session_state[key] = options[0]
        return st.selectbox(label, options, key=key)

    # Mehrere Optionen
    return st.selectbox(
        label,
        options,
        index=None,
        placeholder=placeholder,
        key=key,
    )


@st.cache_data(ttl=300)
def get_fuel_prices() -> dict:
    """
    Holt Preise für mehrere Tankstellen-IDs über die Tankerkönig-API.

    Rückgabewert:
      - Dict mit Station-ID → Preisinformationen
      - leeres Dict bei Fehlern (Netzwerk, API, etc.)
    """
    try:
        stations = load_stations()
    except Exception:
        return {}

    id_liste = [s.get("id") for s in stations if s.get("id")]
    if not id_liste:
        return {}

    try:
        response = requests.get(
            f"{API_BASE}/prices.php",
            params={"ids": ",".join(id_liste), "apikey": API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return {}

    if not data.get("ok"):
        return {}

    prices = data.get("prices", {})
    # Nur offene Tankstellen berücksichtigen
    return {
        sid: info
        for sid, info in prices.items()
        if info.get("status") == "open"
    }


@st.cache_data(ttl=300)
def get_fuel_stats() -> dict:
    """
    Aggregiert min/avg/max für e5, e10 und diesel basierend auf Tankerkönig-Daten.

    Gibt ein Dict der Form:
      {"min": {...}, "avg": {...}, "max": {...}}
    zurück und wirft RuntimeError bei fehlenden Daten.
    """
    prices = get_fuel_prices()
    if not prices:
        raise RuntimeError("Keine Preise von Tankerkönig erhalten.")

    kraftstoffe = ("e5", "e10", "diesel")
    stats = {"min": {}, "avg": {}, "max": {}}

    for fuel in kraftstoffe:
        values = [
            round(float(info[fuel]), 3)
            for info in prices.values()
            if fuel in info and info[fuel] is not None
        ]
        if not values:
            stats["min"][fuel] = stats["avg"][fuel] = stats["max"][fuel] = None
            continue

        stats["min"][fuel] = min(values)
        stats["avg"][fuel] = round(sum(values) / len(values), 3)
        stats["max"][fuel] = max(values)

    return stats


def berechne_kosten(row: pd.Series) -> pd.Series:
    """
    Berechnet Leasing- und Betriebskosten auf Basis einer Zeile aus dem Ranking-DataFrame.

    Erwartete Spalten:
      - UVP
      - Laufzeit_Monate
      - Freikilometer
      - Leasingrate_Faktor
      - Verbrauch_L_100
      - Verbrauch_kWh_100
      - Kraftstoff
      - Sprit (Schlüssel in spritpreise)

    nutzt die globale spritpreise-Tabelle.
    """
    kraftstoff = str(row["Kraftstoff"]).lower()
    uvp = float(row["UVP"])
    laufzeit = int(row["Laufzeit_Monate"])
    km_gesamt = float(row["Freikilometer"])
    leasingrate_faktor = float(row["Leasingrate_Faktor"])
    verbrauch_l = float(row.get("Verbrauch_L_100", 0.0))
    verbrauch_kwh = float(row.get("Verbrauch_kWh_100", 0.0))
    sprit = row["Sprit"]

    leasingkosten_pro_monat = uvp * leasingrate_faktor

    if laufzeit <= 0:
        # Laufzeit 0 oder negativ → nur monatliche Leasingkosten, Rest 0
        return pd.Series(
            {
                "Leasingkosten / Monat": round(leasingkosten_pro_monat, 2),
                "Leasingkosten (Gesamt)": 0.0,
                "Spritkosten / Monat": 0.0,
                "Spritkosten (Gesamt)": 0.0,
                "Gesamtkosten / Monat": round(leasingkosten_pro_monat, 2),
                "Kosten (Gesamt)": 0.0,
            }
        )

    spritkosten_pro_monat = 0.0

    if kraftstoff in ("benzin", "diesel"):
        spritpreis = spritpreise.get(sprit, 0.0)
        spritkosten_pro_monat = km_gesamt / 100.0 * verbrauch_l * spritpreis / laufzeit

    elif kraftstoff == "elektro":
        strompreis = spritpreise.get("Strom", 0.0)
        spritkosten_pro_monat = km_gesamt / 100.0 * verbrauch_kwh * strompreis / laufzeit

    elif kraftstoff in ("elektro/hybrid", "hybrid"):
        spritpreis = spritpreise.get(sprit, 0.0)
        strompreis = spritpreise.get("Strom", 0.0)
        kosten_benzin = km_gesamt / 100.0 * verbrauch_l * spritpreis / laufzeit
        kosten_strom = km_gesamt / 100.0 * verbrauch_kwh * strompreis / laufzeit
        spritkosten_pro_monat = kosten_benzin + kosten_strom

    leasingkosten_gesamt = leasingkosten_pro_monat * laufzeit
    spritkosten_gesamt = spritkosten_pro_monat * laufzeit
    gesamtkosten_pro_monat = leasingkosten_pro_monat + spritkosten_pro_monat
    kosten_gesamt = gesamtkosten_pro_monat * laufzeit

    return pd.Series(
        {
            "Leasingkosten / Monat": round(leasingkosten_pro_monat, 2),
            "Leasingkosten (Gesamt)": round(leasingkosten_gesamt, 2),
            "Spritkosten / Monat": round(spritkosten_pro_monat, 2),
            "Spritkosten (Gesamt)": round(spritkosten_gesamt, 2),
            "Gesamtkosten / Monat": round(gesamtkosten_pro_monat, 2),
            "Kosten (Gesamt)": round(kosten_gesamt, 2),
        }
    )


# =====================================================================
# Daten laden & Session-Setup
# =====================================================================

autos, leasing = load_data()

if "ranking" not in st.session_state:
    st.session_state["ranking"] = []  # Liste von Dicts


# =====================================================================
# Header
# =====================================================================

st.markdown("<h1 style='text-align: center;'>🚗 Leasing Rechner App</h1>", unsafe_allow_html=True)
st.markdown("---")


# =====================================================================
# Aktuelle Spritpreise (Tankerkönig + Fallback)
# =====================================================================

# Referenzposition, aktuell nur dokumentiert
WOB_LAT = 52.423
WOB_LNG = 10.787
RADIUS_KM = 15.0

tanker_preise: dict[str, float] = {}

# Kategorieabhängige Fallback-Preise (min/avg/max)
all_fallback_spritpreise = {
    "min": {
        "Super E10": 1.68,
        "Super E5":  1.75,
        "Super+":    1.95,
        "Diesel":    1.55,
    },
    "avg": {
        "Super E10": 1.78,
        "Super E5":  1.85,
        "Super+":    2.05,
        "Diesel":    1.65,
    },
    "max": {
        "Super E10": 1.88,
        "Super E5":  1.95,
        "Super+":    2.15,
        "Diesel":    1.75,
    },
}

col1, col2 = st.columns(2)
with col1:
    price_category = st.radio(
        "Welche Spritpreise sollen es sein ? 👇",
        ["Günstigste", "Durchschnittliche", "Teuerste"],
        index=1,
        key="price_category",
        horizontal=True,
    )
with col2:
    strom = st.slider("Wie hoch soll der Strompreis sein? ⚡️", 0.00, 1.00, 0.30)

if price_category == "Günstigste":
    st.markdown(
        "<h2 style='text-align: center;'>⛽ Günstigste Spritpreise im Raum Wolfsburg 📉</h2>",
        unsafe_allow_html=True,
    )
    stats_key = "min"
elif price_category == "Durchschnittliche":
    st.markdown(
        "<h2 style='text-align: center;'>⛽ Durchschnittliche Spritpreise im Raum Wolfsburg</h2>",
        unsafe_allow_html=True,
    )
    stats_key = "avg"
else:
    st.markdown(
        "<h2 style='text-align: center;'>⛽ Teuerste Spritpreise im Raum Wolfsburg 📈</h2>",
        unsafe_allow_html=True,
    )
    stats_key = "max"

# Fallback-Werte passend zur ausgewählten Kategorie
fallback_spritpreise = all_fallback_spritpreise.get(
    stats_key,
    all_fallback_spritpreise["avg"],
)

try:
    fuel_stats = get_fuel_stats()
    tanker_preise = fuel_stats.get(stats_key, {})

    # Basispreise mit Fallback
    e10_price = tanker_preise.get("e10") or fallback_spritpreise["Super E10"]
    e5_price = tanker_preise.get("e5") or fallback_spritpreise["Super E5"]
    diesel_price = tanker_preise.get("diesel") or fallback_spritpreise["Diesel"]

    # Super+ als Zuschlag zu Super E5
    super_plus_price = e5_price + 0.10

    spritpreise = {
        "Super E10": e10_price,
        "Super E5": e5_price,
        "Super+": super_plus_price,
        "Diesel": diesel_price,
        "Strom": strom,
    }

except Exception as e:
    st.error(f"Tankerkönig-API nicht erreichbar, es werden definierte Fallback-Werte genutzt. ({e})")
    spritpreise = {
        **fallback_spritpreise,
        "Strom": strom,
    }

cols = st.columns(len(spritpreise))
for i, (sorte, preis) in enumerate(spritpreise.items()):
    if sorte != "Strom":
        cols[i].markdown(
            f"""
            <div style='text-align: center; background-color: black; color: white; font-family: monospace; font-size: 16px; padding: 10px; border-radius: 8px;'>
                {sorte}<br><span style='font-size:36px; color: lime'>{preis:.2f} €</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        cols[i].markdown(
            f"""
            <div style='text-align: center; background-color: black; color: white; font-family: monospace; font-size: 16px; padding: 10px; border-radius: 8px;'>
                {sorte}<br><span style='font-size:36px; color: yellow'>{preis:.2f} €</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.caption(
    "\\* Kraftstoffpreise: E5, E10 und Diesel basieren auf Daten von "
    "[www.tankerkoenig.de](https://www.tankerkoenig.de) "
    "und können zeitlich verzögert oder bereits veraltet sein. "
    "Der Preis für Super+ wird aus Super E5 abgeleitet, der Strompreis wird manuell festgelegt. "
    "Alle Angaben ohne Gewähr."
)

st.markdown("---")


# =====================================================================
# Ranking
# =====================================================================

st.markdown(
    "<h2 style='text-align: center;'>🏆 Ranking</h2>",
    unsafe_allow_html=True,
)

if st.session_state["ranking"]:
    raw_df = pd.DataFrame(st.session_state["ranking"])

    kosten_df = raw_df.apply(berechne_kosten, axis=1)
    ranking_df = pd.concat([raw_df, kosten_df], axis=1)

    ranking_df = ranking_df.sort_values("Gesamtkosten / Monat", ascending=True)

    relevante_spalten = [
        "Bild",
        "Slot",
        "Modell",
        "Ausstattungslinie",
        "Motor",
        "UVP",
        "Leasingoption",
        "Kraftstoff",
        "Sprit",
        "Leasingkosten / Monat",
        "Leasingkosten (Gesamt)",
        "Spritkosten / Monat",
        "Spritkosten (Gesamt)",
        "Gesamtkosten / Monat",
        "Kosten (Gesamt)",
        "Beschreibung",
    ]

    geld_spalten = [
        "UVP",
        "Leasingkosten / Monat",
        "Leasingkosten (Gesamt)",
        "Spritkosten / Monat",
        "Spritkosten (Gesamt)",
        "Gesamtkosten / Monat",
        "Kosten (Gesamt)",
    ]

    st.dataframe(
        ranking_df[relevante_spalten],
        column_config={
            "Bild": st.column_config.ImageColumn(),
            **{
                col: st.column_config.NumberColumn(format="€%d")
                for col in geld_spalten
            },
        },
    )

    st.caption(
        "\\* Fahrzeug- und Leasingdaten basieren auf internen Datenquellen "
        "und können unvollständig oder nicht mehr aktuell sein. "
        "Es handelt sich um unverbindliche Beispielrechnungen. "
        "Maßgeblich sind die offiziellen Angaben des Herstellers oder Anbieters. "
        "Alle Angaben ohne Gewähr."
    )

else:
    st.info("Es befindet sich noch kein Fahrzeug im Ranking.")

st.markdown("---")


# =====================================================================
# Autoauswahl (2 Reihen mit je 4 Autos = 8 Autos)
# =====================================================================

st.markdown(
    "<h2 style='text-align: center;'>🚘 Autoauswahl</h2>",
    unsafe_allow_html=True,
)

cars_per_row = 4
rows = 2

for row_idx in range(rows):
    auto_cols = st.columns(cars_per_row)

    for i in range(cars_per_row):
        car_index = row_idx * cars_per_row + i

        with auto_cols[i]:
            st.markdown(
                f"<h2 style='text-align: center; font-size:20px;'>Auto {car_index + 1}</h2>",
                unsafe_allow_html=True,
            )

            # Modell-Selectbox (Auswahlpflicht)
            modelle = autos["Modell"].unique()
            selected_model = st.selectbox(
                "Modell",
                modelle,
                index=None,
                placeholder="Bitte wählen",
                key=f"modell_{car_index}",
            )

            # Ausstattungslinie, auto-select bei genau einer Option
            if selected_model:
                variationen = autos[autos["Modell"] == selected_model][
                    "Ausstattungslinie"
                ].unique()
            else:
                variationen = []

            selected_variation = auto_selectbox_single(
                "Ausstattungslinie",
                variationen,
                key=f"variation_{car_index}",
                placeholder="Bitte wählen",
            )

            # Motor, auto-select bei genau einer Option
            if selected_model and selected_variation:
                motoren = autos[
                    (autos["Modell"] == selected_model)
                    & (autos["Ausstattungslinie"] == selected_variation)
                ]["Motor"].unique()
            else:
                motoren = []

            selected_engine = auto_selectbox_single(
                "Motor",
                motoren,
                key=f"motor_{car_index}",
                placeholder="Bitte wählen",
            )

            # Motorinfos vorbereiten
            motor_info = pd.DataFrame()
            has_motor = False
            bild = ""
            kraftstoff = None
            verbrauch_l_default = 0.0
            verbrauch_kwh_default = 0.0
            uvp_default = 0

            if selected_engine:
                motor_info = autos[
                    (autos["Modell"] == selected_model)
                    & (autos["Ausstattungslinie"] == selected_variation)
                    & (autos["Motor"] == selected_engine)
                ]
                if not motor_info.empty:
                    has_motor = True
                    row_info = motor_info.iloc[0]
                    bild = row_info.get("Bild", "")
                    kraftstoff = row_info["Kraftstoff"]
                    uvp_default = int(row_info.get("Preis", 0))
                    verbrauch_l_default = float(row_info["l/100km"])
                    verbrauch_kwh_default = float(row_info["kWh/100km"])

            # UVP-Eingabe (bei fehlenden Daten deaktiviert)
            uvp = st.number_input(
                "UVP (in €)",
                value=uvp_default,
                min_value=0,
                step=1000,
                key=f"uvp_{car_index}",
                disabled=not has_motor,
            )

            # Kraftstoff + Verbrauchseingaben
            sprit_arten = ["Super E10", "Super E5", "Super+"]
            selected_sprit = None
            verbrauch_input = 0.0       # L/100km
            verbrauch_input_strom = 0.0 # kWh/100km

            if has_motor:
                kf = kraftstoff.lower()

                if kf == "benzin":
                    selected_sprit = auto_selectbox_single(
                        "Kraftstoff",
                        sprit_arten,
                        key=f"sprit_{car_index}",
                        placeholder="Bitte wählen",
                    )
                    st.markdown("**Verbrenner:**")
                    verbrauch_input = st.number_input(
                        "Verbrauch (L/100km)",
                        value=round(verbrauch_l_default, 1),
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_l_{car_index}",
                    )
                    verbrauch_input_strom = 0.0

                elif kf == "diesel":
                    selected_sprit = auto_selectbox_single(
                        "Kraftstoff",
                        ["Diesel"],
                        key=f"sprit_{car_index}",
                        placeholder="Bitte wählen",
                    )
                    st.markdown("**Verbrenner:**")
                    verbrauch_input = st.number_input(
                        "Verbrauch (L/100km)",
                        value=round(verbrauch_l_default, 1),
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_l_{car_index}",
                    )
                    verbrauch_input_strom = 0.0

                elif kf == "elektro":
                    selected_sprit = auto_selectbox_single(
                        "Kraftstoff",
                        ["Strom"],
                        key=f"sprit_{car_index}",
                        placeholder="Bitte wählen",
                    )
                    verbrauch_input = 0.0
                    st.markdown("**E-Motor:**")
                    verbrauch_input_strom = st.number_input(
                        "Verbrauch (kWh/100km)",
                        value=round(verbrauch_kwh_default, 1),
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_kwh_{car_index}",
                    )

                elif kf in ("elektro/hybrid", "hybrid"):
                    selected_sprit = auto_selectbox_single(
                        "Kraftstoff",
                        sprit_arten,
                        key=f"sprit_{car_index}",
                        placeholder="Bitte wählen",
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Verbrenner:**")
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=round(verbrauch_l_default, 1),
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_l_{car_index}",
                        )
                    with c2:
                        st.markdown("**E-Motor:**")
                        verbrauch_input_strom = st.number_input(
                            "Verbrauch (kWh/100km)",
                            value=round(verbrauch_kwh_default, 1),
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_kwh_{car_index}",
                        )
                else:
                    # Unbekannter Kraftstoff → Eingaben werden deaktiviert
                    st.selectbox(
                        "Kraftstoff",
                        [],
                        index=None,
                        placeholder="Keine Daten",
                        key=f"sprit_{car_index}",
                        disabled=True,
                    )
                    verbrauch_input = st.number_input(
                        "Verbrauch (L/100km)",
                        value=0.0,
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_l_{car_index}",
                        disabled=True,
                    )
                    verbrauch_input_strom = st.number_input(
                        "Verbrauch (kWh/100km)",
                        value=0.0,
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_kwh_{car_index}",
                        disabled=True,
                    )
            else:
                # Ohne Motor-Auswahl werden Verbrauchs-Eingaben deaktiviert dargestellt
                st.selectbox(
                    "Kraftstoff",
                    [],
                    index=None,
                    placeholder="Bitte zuerst Motor wählen",
                    key=f"sprit_{car_index}",
                    disabled=True,
                )
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Verbrenner:**")
                    verbrauch_input = st.number_input(
                        "Verbrauch (L/100km)",
                        value=0.0,
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_l_{car_index}",
                        disabled=True,
                    )
                with c2:
                    st.markdown("**E-Motor:**")
                    verbrauch_input_strom = st.number_input(
                        "Verbrauch (kWh/100km)",
                        value=0.0,
                        min_value=0.0,
                        step=0.1,
                        format="%.1f",
                        key=f"verbrauch_kwh_{car_index}",
                        disabled=True,
                    )

            # Leasingoptionen nach Kategorie des Motors filtern
            passende_leasing = pd.DataFrame()
            if has_motor:
                kategorie = motor_info["Kategorie"].values[0]  # z. B. Verbrenner / Elektro/Hybrid
                motor_str = motor_info["Motor"].values[0]

                bedingung_kraftstoff, bedingung_modell = find_leasing_bedingung(
                    leasing, kategorie, selected_model
                )

                passende_leasing = leasing[
                    (leasing["Bedingung Kraftstoff"] == bedingung_kraftstoff)
                    & (leasing["Bedingung Modell"] == bedingung_modell)
                ]

            leasing_options = (
                passende_leasing["Leasingoption"].unique()
                if not passende_leasing.empty
                else []
            )

            selected_leasing = auto_selectbox_single(
                "Leasingoption",
                leasing_options,
                key=f"leasing_{car_index}",
                placeholder="Bitte wählen",
            )

            # Freikilometer / Laufzeit / Rate für Kostenberechnung
            standard_km = 15000
            laufzeit = 6
            standard_rate = 0.9

            c1, c2, c3 = st.columns(3)

            if selected_leasing:
                leasing_row_pre = passende_leasing[
                    passende_leasing["Leasingoption"] == selected_leasing
                ]
                if not leasing_row_pre.empty:
                    leasing_row_pre = leasing_row_pre.iloc[0]
                    standard_km = leasing_row_pre["Freikilometer"]
                    laufzeit = int(leasing_row_pre["Laufzeit"])
                    standard_rate = float(leasing_row_pre["Leasingrate"])

                with c1:
                    adjusted_rate = st.number_input(
                        "Rate anpassen",
                        value=float(standard_rate),
                        min_value=0.1,
                        max_value=1.0,
                        step=0.1,
                        format="%.1f",
                        key=f"rate_{car_index}",
                    )
                with c2:
                    adjusted_time = st.number_input(
                        "Laufzeit anpassen",
                        value=int(laufzeit),
                        min_value=6,
                        max_value=12,
                        step=6,
                        key=f"time_{car_index}",
                    )
                with c3:
                    adjusted_km = st.number_input(
                        "Kilometer anpassen",
                        value=int(standard_km),
                        min_value=0,
                        step=1000,
                        key=f"km_{car_index}",
                    )
            else:
                with c1:
                    adjusted_rate = st.number_input(
                        "Rate anpassen",
                        value=0.0,
                        format="%.1f",
                        key=f"rate_{car_index}",
                        disabled=True,
                    )
                with c2:
                    adjusted_time = st.number_input(
                        "Laufzeit anpassen",
                        value=0,
                        key=f"time_{car_index}",
                        disabled=True,
                    )
                with c3:
                    adjusted_km = st.number_input(
                        "Kilometer anpassen",
                        value=0,
                        key=f"km_{car_index}",
                        disabled=True,
                    )

            # Beschreibungstext
            st.markdown("**Optional:**")
            description = st.text_area(
                "Kurze Beschreibung des Fahrzeugs",
                placeholder="z.B. besondere Ausstattung, Farbe, Optionen ...",
                max_chars=100,
                key=f"description_{car_index}",
            )

            # Fahrzeug ins Ranking übernehmen
            if st.button("Ranking aktualisieren", key=f"rank_{car_index}"):
                if not (
                    selected_model
                    and selected_variation
                    and selected_engine
                    and selected_leasing
                    and has_motor
                ):
                    st.warning(
                        "Für dieses Fahrzeug werden Modell, Ausstattungslinie, Motor und Leasingoption benötigt."
                    )
                else:
                    leasing_row = passende_leasing[
                        passende_leasing["Leasingoption"] == selected_leasing
                    ]
                    if leasing_row.empty:
                        st.error(
                            "Leasingdaten nicht gefunden. Prüfen, ob leasing.csv und 'Leasingoption' zusammenpassen."
                        )
                    else:
                        leasingrate_faktor = adjusted_rate / 100  # z. B. 0,9 → 0,009
                        laufzeit_monate = adjusted_time
                        freikilometer = adjusted_km

                        # bestehenden Eintrag für diesen Slot entfernen
                        st.session_state["ranking"] = [
                            r
                            for r in st.session_state["ranking"]
                            if r.get("Slot") != car_index + 1
                        ]

                        # neuen Eintrag hinzufügen
                        st.session_state["ranking"].append(
                            {
                                "Bild": bild,
                                "Slot": car_index + 1,
                                "Modell": selected_model,
                                "Ausstattungslinie": selected_variation,
                                "Motor": selected_engine,
                                "UVP": uvp,
                                "Leasingoption": selected_leasing,
                                "Freikilometer": freikilometer,
                                "Kraftstoff": kraftstoff,
                                "Sprit": selected_sprit,
                                "Beschreibung": description,
                                "Verbrauch_L_100": verbrauch_input,
                                "Verbrauch_kWh_100": verbrauch_input_strom,
                                "Laufzeit_Monate": laufzeit_monate,
                                "Leasingrate_Faktor": leasingrate_faktor,
                            }
                        )

                        st.success("Fahrzeug im Ranking gespeichert.")
                        st.rerun()
