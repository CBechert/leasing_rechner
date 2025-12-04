import pandas as pd
import streamlit as st
from src.config import PROCESSED_DIR
from src.data_loader import load_engines
from src.data_transform import export_final_engine_csv

def get_leasing_bedingung(modell: str, kategorie: str, motor: str) -> str:
    """
    modell: z.B. 'Golf', 'Tiguan', 'Caddy', 'ID. Buzz', ...
    kategorie: 'Verbrenner' oder 'Elektro/Hybrid' (aus autos.csv)
    motor: kompletter Motor-String, um eHybrid zu erkennen
    """

    # Verbrenner-Regeln
    if kategorie == "Verbrenner":
        # Nutzfahrzeug-Sonderfälle
        if modell in {"Caddy", "Multivan", "California", "Grand California"}:
            return f"Verbrenner|{modell}"

        # Restliche Verbrenner (PKW etc.)
        return "Verbrenner|Rest"

    # Elektro/Hybrid-Regeln
    if kategorie == "Elektro/Hybrid":
        # Sonderfall Golf eHybrid / Tiguan eHybrid
        if modell == "Golf" and "eHybrid" in motor:
            return "Elektro/Hybrid|Golf"
        if modell == "Tiguan" and "eHybrid" in motor:
            return "Elektro/Hybrid|Tiguan"

        # Nutzfahrzeug-Elektro/Hybrid (Caddy eHybrid, Multivan eHybrid, California eHybrid, ID. Buzz)
        if modell in {"Caddy", "Multivan", "California", "ID. Buzz"}:
            return f"Elektro/Hybrid|{modell}"

        # Restliche Elektro/Hybrid (ID.3, ID.4, ID.5, Passat eHybrid etc.)
        return "Elektro/Hybrid|Rest"

    # Fallback
    return "Verbrenner|Rest"


# --- Page setup (muss vor dem ersten Streamlit-Output kommen) ---
st.set_page_config(
    page_title="Leasing Rechner",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Daten laden + ETL, mit Cache ---
@st.cache_data
def load_data():
    # ETL-Pipeline
    load_engines()
    export_final_engine_csv()

    autos = pd.read_csv(f"{PROCESSED_DIR}/autos.csv", sep=";")
    leasing = pd.read_csv(f"{PROCESSED_DIR}/leasing.csv", sep=";")

    # Verbrauchsspalten sicher numerisch
    autos["l/100km"] = pd.to_numeric(autos["l/100km"], errors="coerce").fillna(0.0)
    autos["kWh/100km"] = pd.to_numeric(autos["kWh/100km"], errors="coerce").fillna(0.0)

    # Leasingraten + Laufzeit numerisch
    leasing["Leasingrate"] = pd.to_numeric(leasing["Leasingrate"], errors="coerce").fillna(0.0)
    leasing["Laufzeit"] = pd.to_numeric(leasing["Laufzeit"], errors="coerce").fillna(0)

    return autos, leasing

autos, leasing = load_data()

# --- Ranking-State in Session ---
if "ranking" not in st.session_state:
    st.session_state["ranking"] = []  # Liste von Dicts

# --- Überschrift ---
st.markdown("<h1 style='text-align: center;'>🚗 Leasing Rechner App</h1>", unsafe_allow_html=True)
st.markdown("---")

# --- Aktuelle Spritpreise (Dummy-Werte) ---
spritpreise = {
    "Super E10": 1.78,
    "Super E5": 1.85,
    "Super+": 2.05,
    "Diesel": 1.65,
    "Strom": 0.30,
}

st.markdown("<h2 style='text-align: center;'>⛽ Aktuelle Spritpreise</h2>", unsafe_allow_html=True)

cols = st.columns(len(spritpreise))
for i, (sorte, preis) in enumerate(spritpreise.items()):
    cols[i].markdown(
        f"""
        <div style='text-align: center; background-color: black; color: white; font-family: monospace; font-size: 16px; padding: 10px; border-radius: 8px;'>
            {sorte}<br><span style='font-size:36px; color: lime'>{preis:.2f} €</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")


# --- Ranking ---
st.markdown("---")
st.markdown(
    "<h2 style='text-align: center;'>🏆 Ranking</h2>", unsafe_allow_html=True
)

if st.session_state["ranking"]:
    ranking_df = pd.DataFrame(st.session_state["ranking"])

    # Standard: nach Gesamtkosten / Monat sortieren
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

    
    st.dataframe(ranking_df,
                 column_config= {col: st.column_config.NumberColumn(format="€%d") for col in geld_spalten}
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

            # Auswahl des Modells
            modelle = autos["Modell"].unique()
            selected_model = st.selectbox(
                "Modell",
                modelle,
                index=None,
                placeholder="Bitte wählen",
                key=f"modell_{car_index}",
            )

            # Auswahl der Ausstattungslinie basierend auf Modell
            variationen = (
                autos[autos["Modell"] == selected_model]["Ausstattungslinie"].unique()
                if selected_model
                else []
            )
            selected_variation = st.selectbox(
                "Ausstattungslinie",
                variationen,
                index=None,
                placeholder="Bitte wählen",
                key=f"variation_{car_index}",
            )

            # Auswahl der Motorisierung basierend auf Modell und Ausstattung
            motoren = (
                autos[
                    (autos["Modell"] == selected_model)
                    & (autos["Ausstattungslinie"] == selected_variation)
                ]["Motor"].unique()
                if selected_variation
                else []
            )
            selected_engine = st.selectbox(
                "Motor",
                motoren,
                index=None,
                placeholder="Bitte wählen",
                key=f"motor_{car_index}",
            )
            

            # Anzeige UVP + Kraftstoffart + Verbrauch
            kraftstoff = None
            selected_sprit = None
            verbrauch_input = 0.0
            verbrauch_input_strom = 0.0
            default_uvp = 30000

            if selected_engine:
                motor_info = autos[
                    (autos["Modell"] == selected_model)
                    & (autos["Ausstattungslinie"] == selected_variation)
                    & (autos["Motor"] == selected_engine)
                ]
                if not motor_info.empty:
                    if "Preis" in motor_info.columns:
                        default_uvp = float(motor_info["Preis"].values[0])
                    # Eingabe der UVP
                    uvp = st.number_input(
                        "UVP (in €)",
                        value=int(default_uvp),
                        min_value=0,
                        step=1000,
                        key=f"uvp_{car_index}",
                    )
                    kraftstoff = motor_info["Kraftstoff"].values[0]
                    verbrauch_l = float(motor_info["l/100km"].values[0])
                    verbrauch_kwh = float(motor_info["kWh/100km"].values[0])
                    sprit_arten = ["Super E10", "Super E5", "Super+"]

                    if kraftstoff.lower() == "benzin":
                        selected_sprit = st.selectbox(
                            "Kraftstoff",
                            sprit_arten,
                            index=0,
                            key=f"sprit_{car_index}",
                        )
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=round(verbrauch_l, 1),
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_l_{car_index}",
                        )

                    elif kraftstoff.lower() == "diesel":
                        selected_sprit = st.selectbox(
                            "Kraftstoff",
                            ["Diesel"],
                            index=0,
                            key=f"sprit_{car_index}",
                        )
                        verbrauch_input = st.number_input(
                            "Verbrauch (L/100km)",
                            value=round(verbrauch_l, 1),
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_diesel_{car_index}",
                        )

                    elif kraftstoff.lower() == "elektro":
                        selected_sprit = "Strom"  # fix
                        st.selectbox(
                            "Kraftstoff",
                            ["Strom"],
                            index=0,
                            key=f"sprit_{car_index}",
                            disabled=True,
                        )
                        verbrauch_input = st.number_input(
                            "Verbrauch (kWh/100km)",
                            value=round(verbrauch_kwh, 1),
                            min_value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=f"verbrauch_kwh_{car_index}",
                        )

                    elif kraftstoff.lower() in ["elektro/hybrid", "hybrid"]:
                        selected_sprit = st.selectbox(
                            "Kraftstoff",
                            sprit_arten,
                            index=0,
                            key=f"sprit_hybrid_{car_index}",
                        )
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**Verbrenner:**")
                            verbrauch_input = st.number_input(
                                "Verbrauch (L/100km)",
                                value=round(verbrauch_l, 1),
                                min_value=0.0,
                                step=0.1,
                                format="%.1f",
                                key=f"verbrauch_l_hybrid_{car_index}",
                            )
                        with col2:
                            st.markdown("**E-Motor:**")
                            verbrauch_input_strom = st.number_input(
                                "Verbrauch (kWh/100km)",
                                value=round(verbrauch_kwh, 1),
                                min_value=0.0,
                                step=0.1,
                                format="%.1f",
                                key=f"verbrauch_kwh_hybrid_{car_index}",
                            )

            # Leasingoptionen filtern nach Kategorie des gewählten Motors
            passende_leasing = pd.DataFrame()
            if selected_engine:
                motor_info = autos[
                    (autos["Modell"] == selected_model)
                    & (autos["Ausstattungslinie"] == selected_variation)
                    & (autos["Motor"] == selected_engine)
                ]

                if not motor_info.empty:
                    kategorie = motor_info["Kategorie"].values[0]  # Verbrenner / Elektro/Hybrid
                    motor_str = motor_info["Motor"].values[0]
                    bedingung_key = get_leasing_bedingung(selected_model, kategorie, motor_str)

                    passende_leasing = leasing[leasing["Bedingung"] == bedingung_key]
                else:
                    passende_leasing = pd.DataFrame()


            selected_leasing = st.selectbox(
                "Leasingoption",
                passende_leasing["Leasingoption"].unique()
                if not passende_leasing.empty
                else [],
                index=None,
                placeholder="Bitte wählen",
                key=f"leasing_{car_index}",
            )

            adjusted_km = 0
            laufzeit = 0

            if selected_leasing:
                leasing_row_pre = passende_leasing[
                    passende_leasing["Leasingoption"] == selected_leasing
                ]
                if not leasing_row_pre.empty:
                    leasing_row_pre = leasing_row_pre.iloc[0]
                    standard_km = leasing_row_pre["Freikilometer"]
                    laufzeit = int(leasing_row_pre["Laufzeit"])
                else:
                    standard_km = 0
                    laufzeit = 0

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
            if st.button("In Ranking übernehmen", key=f"rank_{car_index}"):
                if not (
                    selected_model
                    and selected_variation
                    and selected_engine
                    and selected_leasing
                    and kraftstoff
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
                            leasingrate_faktor = float(leasing_row["Leasingrate"])/100
                        except KeyError:
                            st.error(
                                "Spalte 'Leasingrate' in leasing.csv nicht gefunden – bitte Spaltennamen im Code anpassen."
                            )
                            leasingrate_faktor = 0.0

                        laufzeit_monate = int(leasing_row["Laufzeit"])
                        km_jahr = adjusted_km

                        # -------------------------
                        # Spritkosten / Monat
                        # -------------------------
                        spritkosten_pro_monat = 0.0

                        if kraftstoff.lower() in ["benzin", "diesel"]:
                            spritpreis = spritpreise.get(selected_sprit, 0.0)
                            spritkosten_pro_monat = (
                                km_jahr / 100.0 * verbrauch_input * spritpreis / 12.0
                            )

                        elif kraftstoff.lower() == "elektro":
                            strompreis = spritpreise.get("Strom", 0.0)
                            spritkosten_pro_monat = (
                                km_jahr / 100.0 * verbrauch_input * strompreis / 12.0
                            )

                        elif kraftstoff.lower() in ["elektro/hybrid", "hybrid"]:
                            spritpreis = spritpreise.get(selected_sprit, 0.0)
                            strompreis = spritpreise.get("Strom", 0.0)
                            kosten_benzin = (
                                km_jahr / 100.0 * verbrauch_input * spritpreis / 12.0
                            )
                            kosten_strom = (
                                km_jahr
                                / 100.0
                                * verbrauch_input_strom
                                * strompreis
                                / 12.0
                            )
                            spritkosten_pro_monat = kosten_benzin + kosten_strom

                        # -------------------------
                        # Leasingkosten / Monat (UVP * Leasingrate-Faktor)
                        # -------------------------
                        leasingkosten_pro_monat = uvp * leasingrate_faktor

                        # Leasingkosten (Gesamt)
                        leasingkosten_gesamt = leasingkosten_pro_monat * laufzeit_monate

                        # Spritkosten (Gesamt)
                        spritkosten_gesamt = spritkosten_pro_monat * laufzeit_monate

                        # Gesamtkosten / Monat
                        gesamtkosten_pro_monat = leasingkosten_pro_monat + spritkosten_pro_monat

                        # Kosten (Gesamt)
                        kosten_gesamt = gesamtkosten_pro_monat * laufzeit_monate

                        # alten Eintrag für diesen Slot entfernen
                        st.session_state["ranking"] = [
                            r
                            for r in st.session_state["ranking"]
                            if r.get("Slot") != car_index + 1
                        ]

                        # neuen Eintrag hinzufügen
                        st.session_state["ranking"].append(
                            {
                                "Slot": car_index + 1,
                                "Modell": selected_model,
                                "Ausstattungslinie": selected_variation,
                                "Motor": selected_engine,
                                "UVP": uvp,
                                "Leasingoption": selected_leasing,
                                "Kraftstoff": kraftstoff,
                                "Sprit": selected_sprit,
                                "Leasingkosten / Monat": round(leasingkosten_pro_monat, 2),
                                "Leasingkosten (Gesamt)": round(leasingkosten_gesamt, 2),
                                "Spritkosten / Monat": round(spritkosten_pro_monat, 2),
                                "Spritkosten (Gesamt)": round(spritkosten_gesamt, 2),
                                "Gesamtkosten / Monat": round(gesamtkosten_pro_monat, 2),
                                "Kosten (Gesamt)": round(kosten_gesamt, 2),
                                "Beschreibung": description,
                            }
                        )

                        st.success("Fahrzeug ins Ranking übernommen.")