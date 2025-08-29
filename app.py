import pandas as pd
import streamlit as st

# --- Daten laden ---
autos = pd.read_csv("autos.csv", sep=";")
leasing = pd.read_csv("leasing.csv", sep=";")

# --- Page setup ---
st.set_page_config(page_title="Leasing Rechner", layout="wide", initial_sidebar_state="expanded")

# Darkmode aktivieren
st.markdown(
    """
    <style>
    body { background-color: #0e1117; color: white; }
    div[data-testid="column"] { background-color: black; color: white; padding: 20px; border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True
)

# --- Überschrift ---
st.markdown("<h1 style='text-align: center;'>🚗 Leasing Rechner App</h1>", unsafe_allow_html=True)
st.markdown("---")
# --- Aktuelle Spritpreise (Dummy-Werte) ---
spritpreise = {
    "Super E10": 1.78,
    "Super E5": 1.85,
    "Super+": 2.05,
    "Diesel": 1.65,
    "Strom": 0.30
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
        unsafe_allow_html=True
    )
st.markdown("---")
# --- Autoauswahl (2 Reihen mit je 4 Autos = 8 Autos gesamt) ---
st.markdown("<h2 style='text-align: center;'>🚘 Autoauswahl</h2>", unsafe_allow_html=True)

cars_per_row = 4
rows = 2

for row in range(rows):
    auto_cols = st.columns(cars_per_row)
    for i in range(cars_per_row):
        car_index = row * cars_per_row + i
        with auto_cols[i]:
            st.markdown(f"<h2 style='text-align: center; font-size:20px;'>Auto {car_index+1}</h2>", unsafe_allow_html=True)
            
            # Beschreibung des Autos
            st.markdown("**Beschreibung:**")
            description = st.text_area(
                "Kurze Beschreibung des Fahrzeugs",
                placeholder="z.B. spezielle Ausstattung, Farbe, Besonderheiten...",
                max_chars=100,
                key=f"description_{car_index}"
            )
            
            # Eingabe der UVP
            uvp = st.number_input(
                "UVP (in €)",
                value=30000,
                min_value=0,
                step=1000,
                key=f"uvp_{car_index}"
            )
            
            # Auswahl des Modells
            modelle = autos["Modell"].unique()
            selected_model = st.selectbox(
                "Modell",
                modelle,
                index=None,
                placeholder="Bitte wählen",
                key=f"modell_{car_index}"
            )

            # Auswahl der Ausstattungslinie basierend auf Modell
            variationen = autos[autos["Modell"] == selected_model]["Ausstattungslinie"].unique() if selected_model else []
            selected_variation = st.selectbox(
                "Ausstattungslinie",
                variationen,
                index=None,
                placeholder="Bitte wählen",
                key=f"variation_{car_index}"
            )

            # Auswahl der Motorisierung basierend auf Modell und Ausstattung
            motoren = autos[(autos["Modell"] == selected_model) & (autos["Ausstattungslinie"] == selected_variation)]["Motor"].unique() if selected_variation else []
            selected_engine = st.selectbox(
                "Motor",
                motoren,
                index=None,
                placeholder="Bitte wählen",
                key=f"motor_{car_index}"
            )

            # Anzeige Kraftstoffart + Verbrauch
            kraftstoff = None
            if selected_engine:
                motor_info = autos[(autos["Modell"] == selected_model) & (autos["Ausstattungslinie"] == selected_variation) & (autos["Motor"] == selected_engine)]
                if not motor_info.empty:
                    kraftstoff = motor_info["Kraftstoff"].values[0]
                    verbrauch_l = motor_info["l/100km"].values[0]
                    verbrauch_kwh = motor_info["kWh/100km"].values[0]

                    if kraftstoff.lower() == "benzin":
                        sprit_arten = ["Super E10", "Super E5", "Super+"]
                        selected_sprit = st.selectbox("Kraftstoff", sprit_arten, index=0, key=f"sprit_{car_index}")
                        verbrauch_input = st.number_input("Verbrauch (L/100km)", value=round(float(verbrauch_l),1), min_value=0.0, step=0.1, format="%.1f", key=f"verbrauch_l_{car_index}")
                    elif kraftstoff.lower() == "diesel":
                        selected_sprit = st.selectbox("Kraftstoff", "Diesel", index=0, key=f"sprit_{car_index}")
                        verbrauch_input = st.number_input("Verbrauch (L/100km)", value=round(float(verbrauch_l),1), min_value=0.0, step=0.1, format="%.1f", key=f"verbrauch_diesel_{car_index}")
                    elif kraftstoff.lower() == "elektro":
                        selected_sprit = st.selectbox("Kraftstoff", "Strom", index=0, key=f"sprit_{car_index}")
                        verbrauch_input = st.number_input("Verbrauch (kWh/100km)", value=round(float(verbrauch_kwh),1), min_value=0.0, step=0.1, format="%.1f", key=f"verbrauch_kwh_{car_index}")
                    elif kraftstoff.lower() == "hybrid":
                        sprit_arten = ["Super E10", "Super E5", "Super+"]
                        selected_sprit = st.selectbox("Kraftstoff", sprit_arten, index=0, key=f"sprit_hybrid_{car_index}")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**Verbrenner:**")
                            verbrauch_input = st.number_input("Verbrauch (L/100km)", value=round(float(verbrauch_l),1), min_value=0.0, step=0.1, format="%.1f", key=f"verbrauch_l_hybrid_{car_index}")
                        with col2:
                            st.markdown("**E-Motor:**")
                            verbrauch_input_strom = st.number_input("Verbrauch (kWh/100km)", value=round(float(verbrauch_kwh),1), min_value=0.0, step=0.1, format="%.1f", key=f"verbrauch_kwh_hybrid_{car_index}")

            # Leasingoptionen filtern nach Kategorie des gewählten Motors
            passende_leasing = []
            if selected_engine:
                motor_kategorie = autos[(autos["Modell"] == selected_model) & (autos["Ausstattungslinie"] == selected_variation) & (autos["Motor"] == selected_engine)]["Kategorie"].values
                if len(motor_kategorie) > 0:
                    passende_leasing = leasing[leasing["Bedingung"] == motor_kategorie[0]]

            selected_leasing = st.selectbox(
                "Leasingoption",
                passende_leasing["Leasingoption"].unique() if len(passende_leasing) > 0 else [],
                index=None,
                placeholder="Bitte wählen",
                key=f"leasing_{car_index}"
            )

            if selected_leasing:
                standard_km = passende_leasing[passende_leasing["Leasingoption"] == selected_leasing]["Freikilometer"].values[0]
                adjusted_km = st.number_input(
                    "Kilometer anpassen",
                    value=int(standard_km),
                    min_value=0,
                    step=1000,
                    key=f"km_{car_index}"
                )

st.markdown("---")
# --- Ranking ---
st.markdown("<h2 style='text-align: center;'>🏆 Ranking</h2>", unsafe_allow_html=True)