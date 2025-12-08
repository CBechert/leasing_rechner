import requests
import json
import pandas as pd
import streamlit as st

from src.config import PROCESSED_DIR, STATIONS_PATH

# --- Page setup (muss vor dem ersten Streamlit-Output kommen) ---
st.set_page_config(
    page_title="Leasing Rechner",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

API_BASE = "https://creativecommons.tankerkoenig.de/json"
API_KEY = st.secrets["tankerkoenig"]["api_key"]


def find_leasing_bedingung(leasing_df, kategorie: str, modell: str) -> str:
    # 1) Versuch: exakte Regel vorhanden?
    mask_exact = (
        (leasing_df["Bedingung Kraftstoff"] == kategorie)
        & (leasing_df["Bedingung Modell"] == modell)
    )
    if leasing_df[mask_exact].shape[0] > 0:
        return kategorie, modell

    # 2) Fallback: "Rest" für diese Kategorie
    mask_rest = (
        (leasing_df["Bedingung Kraftstoff"] == kategorie)
        & (leasing_df["Bedingung Modell"] == "Rest")
    )
    if leasing_df[mask_rest].shape[0] > 0:
        return kategorie, "Rest"

    # 3) ganz harter Fallback
    return kategorie, modell  # oder ( "Verbrenner", "Rest" ) o.ä.


# --- Daten laden + ETL, mit Cache ---
@st.cache_data
def load_data():
    autos = pd.read_csv(f"{PROCESSED_DIR}/autos.csv", sep=";")
    leasing = pd.read_csv(f"{PROCESSED_DIR}/leasing.csv", sep=";")

    # Verbrauchsspalten sicher numerisch
    autos["l/100km"] = pd.to_numeric(autos["l/100km"], errors="coerce").fillna(0.0)
    autos["kWh/100km"] = pd.to_numeric(autos["kWh/100km"], errors="coerce").fillna(0.0)

    # Leasingraten + Laufzeit numerisch
    leasing["Leasingrate"] = pd.to_numeric(leasing["Leasingrate"], errors="coerce").fillna(0.0)
    leasing["Laufzeit"] = pd.to_numeric(leasing["Laufzeit"], errors="coerce").fillna(0)

    return autos, leasing


def load_stations():
    with STATIONS_PATH.open("r", encoding="utf-8") as f:
        stations = json.load(f)
    return stations


def auto_selectbox_single(label: str, options, key: str, placeholder: str | None = None):
    """
    Sonderfall bei Kraftstoff:
    - Immer automatisch ausgewählt
    - Bei Benziner → Super E10 (über Aufrufer geregelt)

    Für Line / Motor / Leasingoption:
    - 0 Optionen  → leere Selectbox (None, mit Placeholder)
    - 1 Option    → automatisch ausgewählt (Session-State wird gesetzt)
    - ≥2 Optionen → leer mit Placeholder
    """
    options = list(options) if options is not None else []

    # Sonderfall
    if label == "Kraftstoff":
        current = st.session_state.get(key, None)
        if current not in options and options:
            st.session_state[key] = options[0]
        return st.selectbox(label, options, key=key)

    # 0 Optionen → leer
    if len(options) == 0:
        return st.selectbox(
            label,
            [],
            index=None,
            placeholder=placeholder,
            key=key,
        )

    # 1 Option → Session-State auf diese Option setzen, falls noch nichts/ungültig
    if len(options) == 1:
        current = st.session_state.get(key, None)
        if current not in options:
            st.session_state[key] = options[0]
        return st.selectbox(label, options, key=key)

    # ≥2 Optionen → leer lassen, Nutzer muss wählen
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
    Holt Preise für mehrere Tankstellen-IDs über /prices.php.
    Gibt {} zurück, wenn irgendwas schiefgeht (DNS, Netzwerk, HTTP, API-Fehler).
    """
    try:
        stations = load_stations()
    except Exception:
        return {}

    id_liste = [station.get("id") for station in stations if station.get("id")]
    if not id_liste:
        return {}

    try:
        r = requests.get(
            f"{API_BASE}/prices.php?ids={','.join(str(x) for x in id_liste)}&apikey={API_KEY}",timeout=10,)
        data = r.json()
    except Exception:
        # DNS / Netzwerk / HTTP-Fehler → keine Preise
        return {}

    if not data.get("ok"):
        return {}

    prices = data["prices"]
    # Nur offene Tankstellen behalten
    open_stations = {
        sid: info for sid, info in prices.items()
        if info.get("status") == "open"
    }
    return open_stations


@st.cache_data(ttl=300)
def get_fuel_stats():
    prices = get_fuel_prices()
    if not prices:
        raise RuntimeError("Keine Preise von Tankerkönig erhalten.")
    kraftstoffe = ["e5", "e10", "diesel"]
    stats = {"min": {}, "avg": {}, "max": {}}

    for fuel in kraftstoffe:
        values = [int(info[fuel] * 100) / 100 for info in prices.values() if fuel in info and info[fuel] is not None]
        if values:
            stats["min"][fuel] = min(values)
            stats["avg"][fuel] = round(sum(values) / len(values), 3)
            stats["max"][fuel] = max(values)
        else:
            stats["min"][fuel] = stats["avg"][fuel] = stats["max"][fuel] = None

    return stats


def berechne_kosten(row: pd.Series) -> pd.Series:
        kraftstoff = str(row["Kraftstoff"]).lower()
        uvp = float(row["UVP"])
        laufzeit = int(row["Laufzeit_Monate"])
        km_gesamt = float(row["Freikilometer"])
        leasingrate_faktor = float(row["Leasingrate_Faktor"])
        verbrauch_l = float(row.get("Verbrauch_L_100", 0.0))
        verbrauch_kwh = float(row.get("Verbrauch_kWh_100", 0.0))
        sprit = row["Sprit"]

        spritkosten_pro_monat = 0.0

        if laufzeit <= 0:
            # Alles 0, wenn Laufzeit kaputt
            leasingkosten_pro_monat = uvp * leasingrate_faktor
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

        if kraftstoff in ["benzin", "diesel"]:
            spritpreis = spritpreise.get(sprit, 0.0)
            spritkosten_pro_monat = (
                km_gesamt / 100.0 * verbrauch_l * spritpreis / laufzeit
            )

        elif kraftstoff == "elektro":
            strompreis = spritpreise.get("Strom", 0.0)
            spritkosten_pro_monat = (
                km_gesamt / 100.0 * verbrauch_kwh * strompreis / laufzeit
            )

        elif kraftstoff in ["elektro/hybrid", "hybrid"]:
            spritpreis = spritpreise.get(sprit, 0.0)
            strompreis = spritpreise.get("Strom", 0.0)
            kosten_benzin = (
                km_gesamt / 100.0 * verbrauch_l * spritpreis / laufzeit
            )
            kosten_strom = (
                km_gesamt / 100.0 * verbrauch_kwh * strompreis / laufzeit
            )
            spritkosten_pro_monat = kosten_benzin + kosten_strom

        # Leasingkosten / Monat
        leasingkosten_pro_monat = uvp * leasingrate_faktor
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
        

# Daten laden
autos, leasing = load_data()

# --- Ranking-State in Session ---
if "ranking" not in st.session_state:
    st.session_state["ranking"] = []  # Liste von Dicts

# --- Überschrift ---
st.markdown("<h1 style='text-align: center;'>🚗 Leasing Rechner App</h1>", unsafe_allow_html=True)
st.markdown("---")

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# --- Aktuelle Spritpreise (Tankerkönig) ---

# Wolfsburg grob als Mittelpunkt (aktuell nicht genutzt, aber lass es drin)
WOB_LAT = 52.423
WOB_LNG = 10.787
RADIUS_KM = 15.0

tanker_preise = {}
fallback_spritpreise = {
    "Super E10": 1.78,
    "Super E5": 1.85,
    "Super+": 2.05,
    "Diesel": 1.65,
}

col1, col2 = st.columns(2)
with col1:
    price_category = st.radio(
        "Welche Spritpreise sollen es sein ? 👇",
        ["Günstigste", "Durchschnittliche", "Teuerste"],
        key="price_category",
        horizontal=True,
    )
with col2:
    strom = st.slider("Wie hoch soll der Strompreis sein? ⚡️", 0.00, 1.00, 0.30)

if price_category == "Günstigste":
    st.markdown("<h2 style='text-align: center;'>⛽ Günstigste Spritpreise im Raum Wolfsburg 📉</h2>", unsafe_allow_html=True)
    stats_key = "min"
elif price_category == "Durchschnittliche":
    st.markdown("<h2 style='text-align: center;'>⛽ Durchschnittliche Spritpreise im Raum Wolfsburg</h2>", unsafe_allow_html=True)
    stats_key = "avg"
else:
    st.markdown("<h2 style='text-align: center;'>⛽ Teuerste Spritpreise im Raum Wolfsburg 📈</h2>", unsafe_allow_html=True)
    stats_key = "max"

try:
    fuel_stats = get_fuel_stats()
    tanker_preise = fuel_stats.get(stats_key, {})
    # tanker_preise: keys e5, e10, diesel → in UI-Namen mappen + Fallback
    spritpreise = {
        "Super E10": tanker_preise.get("e10", fallback_spritpreise["Super E10"]),
        "Super E5": tanker_preise.get("e5", fallback_spritpreise["Super E5"]),
        # Super+ = E5 + 0.10 (oder was du willst)
        "Super+": tanker_preise.get("e5", fallback_spritpreise["Super E5"]) + 0.10,
        "Diesel": tanker_preise.get("diesel", fallback_spritpreise["Diesel"]),
        "Strom": strom,
    }
except Exception as e:
    st.error(f"Tankerkönig-API nicht erreichbar, nutze Backup-Werte. ({e})")
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
    "Der Preis für Super+ wird aus Super E5 geschätzt, der Strompreis wird manuell vom Nutzer festgelegt. "
    "Alle Angaben ohne Gewähr."
)

st.markdown("---")
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# --- Ranking ---
st.markdown("---")
st.markdown(
    "<h2 style='text-align: center;'>🏆 Ranking</h2>", unsafe_allow_html=True
)

if st.session_state["ranking"]:
    raw_df = pd.DataFrame(st.session_state["ranking"])

    kosten_df = raw_df.apply(berechne_kosten, axis=1)
    ranking_df = pd.concat([raw_df, kosten_df], axis=1)

    # Standard: nach Gesamtkosten / Monat sortieren
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
    "\\* Fahrzeug- und Leasingdaten stammen aus eigenen Datenquellen "
    "und können unvollständig oder nicht mehr aktuell sein. "
    "Es handelt sich um unverbindliche Beispielrechnungen – maßgeblich sind stets die offiziellen Angaben "
    "des Herstellers bzw. Anbieters. Alle Angaben ohne Gewähr."
)


else:
    st.info("Bitte mindestens ein Fahrzeug ins Ranking übernehmen.")

# --- Autoauswahl (2 Reihen mit je 4 Autos = 8 Autos gesamt) ---
st.markdown("<h2 style='text-align: center;'>🚘 Autoauswahl</h2>", unsafe_allow_html=True)

cars_per_row = 4
rows = 2

for row in range(rows):
    auto_cols = st.columns(cars_per_row)
    for i in range(cars_per_row):
        car_index = row * cars_per_row + i
        with auto_cols[i]:
            st.markdown(
                f"<h2 style='text-align: center; font-size:20px;'>Auto {car_index+1}</h2>",
                unsafe_allow_html=True,
            )

            # --- Modell: bleibt wie bisher (leer, bis Nutzer wählt) ---
            modelle = autos["Modell"].unique()
            selected_model = st.selectbox(
                "Modell",
                modelle,
                index=None,
                placeholder="Bitte wählen",
                key=f"modell_{car_index}",
            )

            # --- Ausstattungslinie: auto-select wenn genau 1 Option ---
            if selected_model:
                variationen = autos[autos["Modell"] == selected_model]["Ausstattungslinie"].unique()
            else:
                variationen = []

            selected_variation = auto_selectbox_single(
                "Ausstattungslinie",
                variationen,
                key=f"variation_{car_index}",
                placeholder="Bitte wählen",
            )

            # --- Motor: auto-select wenn genau 1 Option ---
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

            # --- Motorinfos vorbereiten ---
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

            # --- UVP immer anzeigen (0, wenn kein Motor gewählt / keine Daten) ---
            uvp = st.number_input(
                "UVP (in €)",
                value=uvp_default,
                min_value=0,
                step=1000,
                key=f"uvp_{car_index}",
                disabled=not has_motor,
            )

            # --- Kraftstoff + Verbrauch: immer Felder anzeigen ---
            sprit_arten = ["Super E10", "Super E5", "Super+"]
            selected_sprit = None
            verbrauch_input = 0.0       # L/100km
            verbrauch_input_strom = 0.0 # kWh/100km

            if has_motor:
                if kraftstoff.lower() == "benzin":
                    # 3 Optionen, immer E10 als Vorauswahl
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

                elif kraftstoff.lower() == "diesel":
                    # Nur Diesel → automatisch ausgewählt
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

                elif kraftstoff.lower() == "elektro":
                    # Nur Strom → automatisch ausgewählt
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

                elif kraftstoff.lower() in ["elektro/hybrid", "hybrid"]:
                    selected_sprit = auto_selectbox_single(
                        "Kraftstoff",
                        sprit_arten,
                        key=f"sprit_{car_index}",
                        placeholder="Bitte wählen",
                    )
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Verbrenner:**")
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=round(verbrauch_l_default, 1),
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_l_{car_index}",
                        )
                    with col2:
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
                    # unbekannter Kraftstoff → alles deaktiviert
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
                # Kein Motor gewählt → Felder anzeigen, aber ohne Auswahl / 0-Werte
                st.selectbox(
                    "Kraftstoff",
                    [],
                    index=None,
                    placeholder="Bitte zuerst Motor wählen",
                    key=f"sprit_{car_index}",
                    disabled=True,
                )
                col1, col2 = st.columns(2)
                with col1:
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
                with col2:
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

            # Leasingoptionen filtern nach Kategorie des gewählten Motors
            passende_leasing = pd.DataFrame()
            if has_motor:
                kategorie = motor_info["Kategorie"].values[0]  # Verbrenner / Elektro/Hybrid
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

            # Leasingoption: auto-select wenn nur 1, sonst leer
            selected_leasing = auto_selectbox_single(
                "Leasingoption",
                leasing_options,
                key=f"leasing_{car_index}",
                placeholder="Bitte wählen",
            )

            # Freikilometer / Laufzeit (für Kostenrechnung)
            standard_km = 0
            laufzeit = 0

            if selected_leasing:
                leasing_row_pre = passende_leasing[
                    passende_leasing["Leasingoption"] == selected_leasing
                ]
                if not leasing_row_pre.empty:
                    leasing_row_pre = leasing_row_pre.iloc[0]
                    standard_km = leasing_row_pre["Freikilometer"]
                    laufzeit = int(leasing_row_pre["Laufzeit"])

            # Kilometer-Eingabe: immer sichtbar, 0 solange keine Leasingoption
            adjusted_km = st.number_input(
                "Kilometer anpassen",
                value=int(standard_km),
                min_value=0,
                step=1000,
                key=f"km_{car_index}",
            )

            # Beschreibung des Autos
            st.markdown("**Optional:**")
            description = st.text_area(
                "Kurze Beschreibung des Fahrzeugs",
                placeholder="z.B. spezielle Ausstattung, Farbe, Besonderheiten...",
                max_chars=100,
                key=f"description_{car_index}",
            )

            # --- Button: Auto ins Ranking übernehmen ---
            if st.button("Ranking aktualisieren", key=f"rank_{car_index}"):
                if not (
                    selected_model
                    and selected_variation
                    and selected_engine
                    and selected_leasing
                    and has_motor
                ):
                    st.warning(
                        "Bitte Modell, Ausstattung, Motor und Leasingoption auswählen."
                    )
                else:
                    leasing_row = passende_leasing[
                        passende_leasing["Leasingoption"] == selected_leasing
                    ]
                    if leasing_row.empty:
                        st.error(
                            "Leasingdaten nicht gefunden. Prüfe leasing.csv / 'Leasingoption'."
                        )
                    else:
                        leasing_row = leasing_row.iloc[0]

                        try:
                            leasingrate_faktor = float(leasing_row["Leasingrate"]) / 100
                        except KeyError:
                            st.error(
                                "Spalte 'Leasingrate' in leasing.csv nicht gefunden – bitte Spaltennamen im Code anpassen."
                            )
                            leasingrate_faktor = 0.0

                        laufzeit_monate = int(leasing_row["Laufzeit"])
                        freikilometer = adjusted_km
                        

                        # alten Eintrag für diesen Slot entfernen
                        st.session_state["ranking"] = [
                            r
                            for r in st.session_state["ranking"]
                            if r.get("Slot") != car_index + 1
                        ]

                        # neuen Eintrag hinzufügen – NUR Basisdaten
                        st.session_state["ranking"].append(
                            {
                                "Bild": bild,
                                "Slot": car_index + 1,
                                "Modell": selected_model,
                                "Ausstattungslinie": selected_variation,
                                "Motor": selected_engine,
                                "UVP": uvp,
                                "Leasingoption": selected_leasing,
                                "Freikilometer":            freikilometer,
                                "Kraftstoff": kraftstoff,
                                "Sprit": selected_sprit,
                                "Beschreibung": description,
                                "Verbrauch_L_100":          verbrauch_input,
                                "Verbrauch_kWh_100":        verbrauch_input_strom,
                                "Laufzeit_Monate":          laufzeit_monate,
                                "Leasingrate_Faktor":       leasingrate_faktor,
                            }
                        )

                        st.success("Fahrzeug ins Ranking übernommen.")
                        st.rerun()
