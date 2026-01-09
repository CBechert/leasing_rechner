import json
import math

import pandas as pd
import requests
import streamlit as st
from streamlit_extras.stylable_container import stylable_container

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

# Farbpalette gemäß Vorgabe
PRIMARY_DEEP = "#002733"
PRIMARY_GREEN = "#008C82"
ACCENT_NEON = "#C2FE06"  # nur auf dunklem Hintergrund nutzen
SECONDARY_CORAL = "#E67364"
SECONDARY_ORANGE = "#FAAA3C"
SECONDARY_BEIGE = "#FAD2AA"
SECONDARY_BLUE = "#8CBEE6"
SECONDARY_VIOLET = "#C882BE"
SECONDARY_LAVENDER = "#DCCDF0"
TRAFFIC_RED = "#DA0C1F"
TRAFFIC_AMBER = "#FCCD22"
TRAFFIC_GREEN = "#63A844"

# Aus Theme lesen (Light/Dark aus config.toml/Streamlit Settings)
theme_base = st.get_option("theme.base") or "dark"
dark_mode = theme_base == "dark"
theme_bg = st.get_option("theme.backgroundColor") or ("#0C1626" if dark_mode else "#FFFFFF")
theme_text = st.get_option("theme.textColor") or ("#E6EEF1" if dark_mode else "#0F1F2F")
secondary_bg = st.get_option("theme.secondaryBackgroundColor") or ("#102537" if dark_mode else "#E7F3F3")
theme_muted = "#9DB2B7" if dark_mode else "#4B5563"
card_border = PRIMARY_GREEN if dark_mode else PRIMARY_DEEP
accent_price = ACCENT_NEON if dark_mode else PRIMARY_GREEN
top_gradient = (
    f"linear-gradient(135deg, {PRIMARY_DEEP}, {PRIMARY_GREEN})"
    if dark_mode
    else "linear-gradient(135deg, #e7f3f3, #cde7e4)"
)
divider_html = f"<hr style='border: 1px solid {card_border}; opacity: 0.3;'/>"

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


def clear_slot_state(slot_id: int) -> None:
    """Entfernt UI-States für einen Slot, ohne andere Slots zu beeinflussen."""
    keys = [
        f"modell_{slot_id}",
        f"variation_{slot_id}",
        f"motor_{slot_id}",
        f"last_motor_{slot_id}",
        f"uvp_{slot_id}",
        f"sprit_{slot_id}",
        f"verbrauch_l_{slot_id}",
        f"verbrauch_kwh_{slot_id}",
        f"leasing_{slot_id}",
        f"rate_{slot_id}",
        f"time_{slot_id}",
        f"km_{slot_id}",
        f"description_{slot_id}",
    ]
    for k in keys:
        if k in st.session_state:
            st.session_state.pop(k)


def auto_selectbox_single(
    label: str,
    options,
    key: str,
    placeholder: str | None = None,
    disabled: bool = False,
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
      - disabled:
          Selectbox bleibt geschlossen, setzt keinen Wert
    """
    options = list(options) if options is not None else []

    if disabled:
        return st.selectbox(
            label,
            options,
            index=None,
            placeholder=placeholder,
            key=key,
            disabled=True,
        )

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

    def geldwerter_vorteil_berechnen() -> tuple[float, float]:
        """
        Geldwerter Vorteil entsteht nur bei Verbrennern mit Leasingrate < 1 %.
        Rückgabe:
          - geldwerter Vorteil pro Monat
          - Steuerlast-Anteil (1/3) pro Monat, der auf die Rate aufgeschlagen wird
        """
        if kraftstoff not in ("benzin", "diesel"):
            return 0.0, 0.0
        if leasingrate_faktor >= 0.01:
            return 0.0, 0.0

        private_nutzung = math.floor(uvp * 0.01)
        leasingrate_abs = uvp * leasingrate_faktor
        geldwerter_vorteil = max(private_nutzung - leasingrate_abs, 0.0)
        steueranteil = geldwerter_vorteil / 3
        return geldwerter_vorteil, steueranteil

    leasingkosten_pro_monat_basis = uvp * leasingrate_faktor
    geldwerter_vorteil, steueranteil = geldwerter_vorteil_berechnen()
    leasingkosten_pro_monat = leasingkosten_pro_monat_basis + steueranteil

    if laufzeit <= 0:
        # Laufzeit 0 oder negativ → nur monatliche Leasingkosten, Rest 0
        return pd.Series(
            {
                "Leasingkosten / Monat": round(leasingkosten_pro_monat, 2),
                "Leasingkosten (Gesamt)": 0.0,
                "Geldwerter Vorteil / Monat": round(geldwerter_vorteil, 2),
                "Steuerlicher Aufschlag / Monat": round(steueranteil, 2),
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
            "Geldwerter Vorteil / Monat": round(geldwerter_vorteil, 2),
            "Steuerlicher Aufschlag / Monat": round(steueranteil, 2),
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
if "ranking_updated" not in st.session_state:
    st.session_state["ranking_updated"] = False
if "ranking_message_slot" not in st.session_state:
    st.session_state["ranking_message_slot"] = None
if "ranking_message_text" not in st.session_state:
    st.session_state["ranking_message_text"] = ""


# =====================================================================
# Header
# =====================================================================

st.markdown(
    f"""
    <style>
    .stApp {{
        background: {theme_bg};
        color: {theme_text};
    }}
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{
        color: {theme_text};
    }}
    .stApp p, .stApp li, .stApp label, .stApp span {{
        color: {theme_text};
    }}
    .stCaption, .stMarkdown span {{
        color: {theme_muted};
    }}
    [data-testid="stHeader"] {{
        background: transparent;
    }}
    button[data-testid="baseButton-primary"] {{
        background: {PRIMARY_GREEN};
        color: #ffffff;
        border-radius: 8px;
        border: none;
    }}
    button[data-testid="baseButton-primary"]:hover {{
        background: {PRIMARY_DEEP};
        color: #ffffff;
    }}
    button[data-testid="baseButton-secondary"] {{
        background: {SECONDARY_CORAL};
        color: #0f1f2f;
        border-radius: 8px;
        border: none;
    }}
    button[data-testid="baseButton-secondary"]:hover {{
        background: {TRAFFIC_RED};
        color: #ffffff;
    }}
    .block-container {{
        padding-top: 0.5rem;
    }}
    input, textarea, select, option, .stTextInput > div > div > input, .stSelectbox > div > div > select {{
        color: {theme_text} !important;
        background-color: {secondary_bg} !important;
    }}
    .stSelectbox > div > div, 
    
    .stNumberInput input, .stTextArea textarea {{
    border: 1px solid {ACCENT_NEON} !important;
    border-radius: 4px !important;
}}

    .stTextArea > div > div {{
        border: 1px solid {ACCENT_NEON} !important;
        border-radius: 4px !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"<h1 style='text-align: center; color:{PRIMARY_GREEN if not dark_mode else ACCENT_NEON};'>🚗 Leasing Rechner App</h1>",
    unsafe_allow_html=True,
)
st.markdown(divider_html, unsafe_allow_html=True)


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
        f"<h2 style='text-align: center; color:{theme_text}; letter-spacing:0.02em;'>⛽ Günstigste Spritpreise im Raum Wolfsburg 📉</h2>",
        unsafe_allow_html=True,
    )
    stats_key = "min"
elif price_category == "Durchschnittliche":
    st.markdown(
        f"<h2 style='text-align: center; color:{theme_text}; letter-spacing:0.02em;'>⛽ Durchschnittliche Spritpreise im Raum Wolfsburg</h2>",
        unsafe_allow_html=True,
    )
    stats_key = "avg"
else:
    st.markdown(
        f"<h2 style='text-align: center; color:{theme_text}; letter-spacing:0.02em;'>⛽ Teuerste Spritpreise im Raum Wolfsburg 📈</h2>",
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
    card_style = (
        f"text-align: center; background: {secondary_bg}; color: {theme_text}; "
        f"font-family: 'Inter', sans-serif; font-size: 16px; padding: 12px; "
        f"border-radius: 12px; border: 1px solid {card_border}; "
        f"box-shadow: 0 10px 24px rgba(0,0,0,0.12);"
    )
    price_color = ACCENT_NEON if dark_mode else PRIMARY_GREEN
    if sorte != "Strom":
        cols[i].markdown(
            f"""
            <div style="{card_style}">
                {sorte}<br><span style='font-size:34px; font-weight:700; color:{price_color};'>{preis:.2f} €</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        cols[i].markdown(
            f"""
            <div style="{card_style}">
                {sorte}<br><span style='font-size:34px; font-weight:700; color:{price_color};'>{preis:.2f} €</span>
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

st.markdown(divider_html, unsafe_allow_html=True)


# =====================================================================
# Ranking
# =====================================================================

st.markdown(
    f"<h2 style='text-align: center; color:{theme_text}; letter-spacing:0.02em;'>🏆 Ranking</h2>",
    unsafe_allow_html=True,
)

if st.session_state["ranking"]:
    raw_df = pd.DataFrame(st.session_state["ranking"])

    kosten_df = raw_df.apply(berechne_kosten, axis=1)
    ranking_df = pd.concat([raw_df, kosten_df], axis=1)

    ranking_df = ranking_df.sort_values("Gesamtkosten / Monat", ascending=True)

    geld_spalten = [
        "UVP",
        "Leasingkosten / Monat",
        "Leasingkosten (Gesamt)",
        "Spritkosten / Monat",
        "Spritkosten (Gesamt)",
        "Gesamtkosten / Monat",
        "Kosten (Gesamt)",
    ]

    # Umschaltbare Ansichten fürs Ranking: kompakt vs. alle Details
    basis_spalten = [
        "Slot",
        "Bild",
        "Modell",
        "Ausstattungslinie",
        "Motor",
        "Kraftstoff",
        "Sprit",
        "Leasingrate_Faktor",
        "Laufzeit_Monate",
        "Freikilometer",
        "UVP",
        "Verbrauch (L/100km)",
        "Verbrauch (kWh/100km)",
        "Leasingkosten / Monat",
        "Leasingkosten (Gesamt)",
        "Geldwerter Vorteil / Monat",
        "Steuerlicher Aufschlag / Monat",
        "Spritkosten / Monat",
        "Spritkosten (Gesamt)",
        "Gesamtkosten / Monat",
        "Kosten (Gesamt)",
        "Beschreibung",
    ]

    rest_spalten = [col for col in ranking_df.columns if col not in basis_spalten]
    alle_spalten = basis_spalten + rest_spalten

    # Top 3 Highlight
    top3 = ranking_df.head(3)
    if not top3.empty:
        top_cols = st.columns(len(top3))
        for idx, (_, row) in enumerate(top3.iterrows()):
            bild = row.get("Bild", "")
            kosten_monat = math.ceil(row.get("Gesamtkosten / Monat", 0) or 0)
            modell = row.get("Modell", "Unbekannt")
            linie = row.get("Ausstattungslinie", "")
            motor = row.get("Motor", "")

            card_html = f"""
            <div style="
                background: {top_gradient};
                color: {theme_text};
                border-radius: 16px;
                padding: 16px;
                box-shadow: 0 12px 30px rgba(0,0,0,0.25);
                text-align: center;
                height: 100%;
            ">
                <div style="font-size: 14px; opacity: 0.8; letter-spacing: 0.05em;">Platz {idx + 1}</div>
                <div style="font-size: 18px; font-weight: 700; margin: 6px 0 2px 0;">{modell}</div>
                <div style="font-size: 18px; font-weight: 700; margin: 6px 0 2px 0;">{linie}</div>
                <div style="font-size: 13px; opacity: 0.8; margin-bottom: 10px;">{motor}</div>
                <div style="margin-bottom: 12px;">
                    {"<img src='" + bild + "' style='max-width:100%; border-radius:12px; background:#ffffff;' />" if bild else f"<div style='height:120px; border-radius:12px; background:{secondary_bg}; display:flex; align-items:center; justify-content:center; color:{theme_muted};'>Kein Bild</div>"}
                </div>
                <div style="font-size: 13px; opacity: 0.8;">Gesamtkosten / Monat</div>
                <div style="font-size: 24px; font-weight: 800; color: {accent_price};">€ {kosten_monat:.0f}</div>
            </div>
            """
            top_cols[idx].markdown(card_html, unsafe_allow_html=True)

    display_df = ranking_df[[c for c in alle_spalten if c in ranking_df.columns]].copy()

    # Leasingfaktor als Dezimalwert (0,9 statt 0,009)
    if "Leasingrate_Faktor" in display_df.columns:
        display_df["Leasingrate_Faktor"] = display_df["Leasingrate_Faktor"] * 100

    # Verbrauchswerte auf eine Nachkommastelle bringen (z. B. 7.0)
    for col in ("Verbrauch_L_100", "Verbrauch_kWh_100"):
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda v: round(float(v), 1) if pd.notna(v) else v
            )

    # Kosten aufrunden (Ganzzahlen) für Anzeige
    kosten_spalten = [
        "UVP",
        "Leasingkosten / Monat",
        "Leasingkosten (Gesamt)",
        "Spritkosten / Monat",
        "Spritkosten (Gesamt)",
        "Gesamtkosten / Monat",
        "Kosten (Gesamt)",
    ]
    for col in kosten_spalten:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda v: math.ceil(float(v)) if pd.notna(v) else v
            )

    # Leasingoption nicht anzeigen
    display_df = display_df.drop(columns=["Leasingoption"], errors="ignore")

    currency_cols_int = [
        "UVP",
        "Leasingkosten / Monat",
        "Leasingkosten (Gesamt)",
        "Spritkosten / Monat",
        "Spritkosten (Gesamt)",
        "Gesamtkosten / Monat",
        "Kosten (Gesamt)",
    ]

    column_config = {"Bild": st.column_config.ImageColumn()}
    column_config.update(
        {
            col: st.column_config.NumberColumn(format="€%.0f")
            for col in currency_cols_int
            if col in display_df.columns
        }
    )
    currency_cols_precise = [
        "Geldwerter Vorteil / Monat",
        "Steuerlicher Aufschlag / Monat",
    ]
    for col in currency_cols_precise:
        if col in display_df.columns:
            column_config[col] = st.column_config.NumberColumn(format="€%.2f")
    if "Freikilometer" in display_df.columns:
        column_config["Freikilometer"] = st.column_config.NumberColumn(format="%.0f")

    for col in ("Verbrauch_L_100", "Verbrauch_kWh_100"):
        if col in display_df.columns:
            column_config[col] = st.column_config.NumberColumn(format="%.1f")

    if "Leasingrate_Faktor" in display_df.columns:
        column_config["Leasingrate_Faktor"] = st.column_config.NumberColumn(format="%.1f")

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    with st.expander("Ausführliches Ranking"):
        st.dataframe(
            display_df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
        )

    st.caption(
        "\\* Fahrzeug- und Leasingdaten basieren auf internen Datenquellen "
        "und können unvollständig oder nicht mehr aktuell sein. "
        "Es handelt sich um unverbindliche Beispielrechnungen. "
        "Maßgeblich sind die offiziellen Angaben des Herstellers oder Anbieters. "
        "Alle Angaben ohne Gewähr."
    )
    st.caption(
        "\\** Die Nutzung eines Fahrzeugs im MA-Leasing (Fahrzeugüberlassung) unterliegt "
        "der Lohnsteuer- und Sozialversicherungspflicht. Für die Berechnung wird "
        "grundsätzlich 1,0 % des UVP/Bruttopreises angesetzt. Liegt die monatliche Rate "
        "unter 1,0 % der UVP, kann ein geldwerter Vorteil entstehen, der individuell zu "
        "versteuern ist. Der angezeigte steuerliche Aufschlag nutzt 1/3 des berechneten "
        "Vorteils als grobe Annahme für die Nettobelastung und kann je nach Steuerklasse, "
        "Freibeträgen und persönlichen Parametern abweichen."
    )

else:
    st.info("Es befindet sich noch kein Fahrzeug im Ranking.")

st.markdown(divider_html, unsafe_allow_html=True)


# =====================================================================
# Autoauswahl (2 Reihen mit je 4 Autos = 8 Autos)
# =====================================================================

st.markdown(
    f"<h2 style='text-align: center; color:{theme_text}; letter-spacing:0.02em;'>🚘 Autoauswahl</h2>",
    unsafe_allow_html=True,
)
cars_per_row = 4
rows = 2

for row_idx in range(rows):
    auto_cols = st.columns(cars_per_row, border=False)

    for i in range(cars_per_row):
        car_index = row_idx * cars_per_row + i
        slot_id = car_index + 1

        with auto_cols[i]:
            with stylable_container(
                key=f"car_card_{slot_id}",
                css_styles=f"""
                    {{
                        border: 2px solid {card_border};
                        border-radius: 12px;
                        padding: 16px;
                        background: {secondary_bg if dark_mode else "#ffffff"};
                        box-shadow: 0 8px 20px rgba(0,0,0,0.12);
                        width: 100%;
                        display: block;
                    }}
                """,
            ):
                st.markdown(
                    f"<h2 style='text-align: center; font-size:20px; color:{theme_text}; margin-top:0;'>Auto {slot_id}</h2>",
                    unsafe_allow_html=True,
                )

                # Modell-Selectbox (Auswahlpflicht)
                modelle = autos["Modell"].unique()
                selected_model = st.selectbox(
                    "Modell",
                    modelle,
                    index=None,
                    placeholder="Bitte wählen",
                    key=f"modell_{slot_id}",
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
                    key=f"variation_{slot_id}",
                    placeholder="Bitte wählen",
                    disabled=not bool(selected_model),
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
                    key=f"motor_{slot_id}",
                    placeholder="Bitte wählen",
                    disabled=not bool(selected_variation),
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
                        uvp_default = int(float(row_info.get("Preis", 0)))
                        verbrauch_l_default = float(row_info["l/100km"])
                        verbrauch_kwh_default = float(row_info["kWh/100km"])

                        last_motor_key = f"last_motor_{slot_id}"
                        if st.session_state.get(last_motor_key) != selected_engine:
                            st.session_state[last_motor_key] = selected_engine
                            st.session_state[f"uvp_{slot_id}"] = uvp_default
                            st.session_state[f"verbrauch_l_{slot_id}"] = round(
                                verbrauch_l_default, 1
                            )
                            st.session_state[f"verbrauch_kwh_{slot_id}"] = round(
                                verbrauch_kwh_default, 1
                            )

                # UVP-Eingabe (bei fehlenden Daten deaktiviert)
                uvp_value = st.session_state.get(f"uvp_{slot_id}", uvp_default)
                uvp = st.number_input(
                    "UVP (in €)",
                    value=uvp_value,
                    min_value=0,
                    step=1000,
                    key=f"uvp_{slot_id}",
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
                            key=f"sprit_{slot_id}",
                            placeholder="Bitte wählen",
                        )
                        st.markdown("**Verbrenner:**")
                        verbrauch_value = st.session_state.get(
                            f"verbrauch_l_{slot_id}", round(verbrauch_l_default, 1)
                        )
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=verbrauch_value,
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_l_{slot_id}",
                        )
                        verbrauch_input_strom = 0.0

                    elif kf == "diesel":
                        selected_sprit = auto_selectbox_single(
                            "Kraftstoff",
                            ["Diesel"],
                            key=f"sprit_{slot_id}",
                            placeholder="Bitte wählen",
                        )
                        st.markdown("**Verbrenner:**")
                        verbrauch_value = st.session_state.get(
                            f"verbrauch_l_{slot_id}", round(verbrauch_l_default, 1)
                        )
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=verbrauch_value,
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_l_{slot_id}",
                        )
                        verbrauch_input_strom = 0.0

                    elif kf == "elektro":
                        selected_sprit = auto_selectbox_single(
                            "Kraftstoff",
                            ["Strom"],
                            key=f"sprit_{slot_id}",
                            placeholder="Bitte wählen",
                        )
                        verbrauch_input = 0.0
                        st.markdown("**E-Motor:**")
                        verbrauch_value_strom = st.session_state.get(
                            f"verbrauch_kwh_{slot_id}", round(verbrauch_kwh_default, 1)
                        )
                        verbrauch_input_strom = st.number_input(
                            "Verbrauch (kWh/100km)",
                            value=verbrauch_value_strom,
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_kwh_{slot_id}",
                        )

                    elif kf in ("elektro/hybrid", "hybrid"):
                        selected_sprit = auto_selectbox_single(
                            "Kraftstoff",
                            sprit_arten,
                            key=f"sprit_{slot_id}",
                            placeholder="Bitte wählen",
                        )
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**Verbrenner:**")
                            verbrauch_value = st.session_state.get(
                                f"verbrauch_l_{slot_id}", round(verbrauch_l_default, 1)
                            )
                            verbrauch_input = st.number_input(
                                "Verbrauch (L/100km)",
                                value=verbrauch_value,
                                min_value=0.0,
                                step=0.1,
                                format="%.1f",
                                key=f"verbrauch_l_{slot_id}",
                            )
                        with c2:
                            st.markdown("**E-Motor:**")
                            verbrauch_value_strom = st.session_state.get(
                                f"verbrauch_kwh_{slot_id}", round(verbrauch_kwh_default, 1)
                            )
                            verbrauch_input_strom = st.number_input(
                                "Verbrauch (kWh/100km)",
                                value=verbrauch_value_strom,
                                min_value=0.0,
                                step=0.1,
                                format="%.1f",
                                key=f"verbrauch_kwh_{slot_id}",
                            )
                    else:
                        # Unbekannter Kraftstoff → Eingaben werden deaktiviert
                        st.selectbox(
                            "Kraftstoff",
                            [],
                            index=None,
                            placeholder="Keine Daten",
                            key=f"sprit_{slot_id}",
                            disabled=True,
                        )
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=0.0,
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_l_{slot_id}",
                            disabled=True,
                        )
                        verbrauch_input_strom = st.number_input(
                            "Verbrauch (kWh/100km)",
                            value=0.0,
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_kwh_{slot_id}",
                            disabled=True,
                        )
                else:
                    # Ohne Motor-Auswahl werden Verbrauchs-Eingaben deaktiviert dargestellt
                    st.selectbox(
                        "Kraftstoff",
                        [],
                        index=None,
                        placeholder="Bitte zuerst Motor wählen",
                        key=f"sprit_{slot_id}",
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
                            key=f"verbrauch_l_{slot_id}",
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
                            key=f"verbrauch_kwh_{slot_id}",
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
                    key=f"leasing_{slot_id}",
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
                            "Rate",
                            value=float(standard_rate),
                            min_value=0.1,
                            max_value=1.0,
                            step=0.1,
                            format="%.1f",
                            key=f"rate_{slot_id}",
                        )
                    with c2:
                        adjusted_time = st.number_input(
                            "Laufzeit",
                            value=int(laufzeit),
                            min_value=6,
                            max_value=12,
                            step=6,
                            key=f"time_{slot_id}",
                        )
                    with c3:
                        adjusted_km = st.number_input(
                            "Kilometer",
                            value=int(standard_km),
                            min_value=0,
                            step=1000,
                            key=f"km_{slot_id}",
                        )
                else:
                    with c1:
                        adjusted_rate = st.number_input(
                            "Rate",
                            value=0.0,
                            format="%.1f",
                            key=f"rate_{slot_id}",
                            disabled=True,
                        )
                    with c2:
                        adjusted_time = st.number_input(
                            "Laufzeit",
                            value=0,
                            key=f"time_{slot_id}",
                            disabled=True,
                        )
                    with c3:
                        adjusted_km = st.number_input(
                            "Kilometer",
                            value=0,
                            key=f"km_{slot_id}",
                            disabled=True,
                        )

                # Beschreibungstext
                st.markdown("**Optional:**")
                description = st.text_area(
                    "Kurze Beschreibung des Fahrzeugs",
                    placeholder="z.B. besondere Ausstattung, Farbe, Optionen ...",
                    max_chars=100,
                    key=f"description_{slot_id}",
                )

                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button(
                        "Ranking aktualisieren",
                        key=f"rank_{slot_id}",
                        type="primary",
                        use_container_width=True,
                    ):
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
                                    if r.get("Slot") != slot_id
                                ]

                                # neuen Eintrag hinzufügen
                                st.session_state["ranking"].append(
                                    {
                                        "Bild": bild,
                                        "Slot": slot_id,
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

                                st.session_state["ranking_updated"] = True
                                st.session_state["ranking_message_slot"] = slot_id
                                st.session_state["ranking_message_text"] = "Ranking wurde aktualisiert."
                                st.rerun()
                with btn_col2:
                    if st.button(
                        "Aus Ranking entfernen",
                        key=f"remove_{slot_id}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        before = len(st.session_state["ranking"])
                        st.session_state["ranking"] = [
                            r for r in st.session_state["ranking"] if r.get("Slot") != slot_id
                        ]
                        if len(st.session_state["ranking"]) != before:
                            st.session_state["ranking_updated"] = True
                            st.session_state["ranking_message_slot"] = slot_id
                            st.session_state["ranking_message_text"] = "Fahrzeug wurde entfernt."
                            clear_slot_state(slot_id)
                            st.rerun()

                    if st.session_state.get("ranking_message_slot") == slot_id:
                        st.info(st.session_state.get("ranking_message_text", ""))
                        st.session_state["ranking_message_slot"] = None
                        st.session_state["ranking_message_text"] = ""
