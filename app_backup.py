# Streamlit Leasingrechner – Mitarbeiterleasing (ein Hersteller)
# --------------------------------------------------------------
# CSV-Formate (Semikolon-getrennt):
# leasing.csv:  Laufzeit;Freikilometer;Leasingrate;Tankguthaben;Bedingung
# autos.csv:    Modell;Ausstattungslinie;Motor;Leistung;Getriebe
#
# Layout: Autos in Reihen von 5 nebeneinander. Wenn alle 5 ausgefüllt,
# erscheint eine neue Reihe mit weiteren 5 Autos (maximal 10 insgesamt).

from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Leasingrechner", page_icon="🚗", layout="wide")

# --------------------------
# Konfiguration
# --------------------------
MAX_CARS = 10
DEFAULT_PRICES = {"Super E5": 1.89, "Super E10": 1.79, "Super+": 2.00, "Diesel": 1.75, "Strom": 0.35}

# --------------------------
# Daten laden
# --------------------------
@st.cache_data(show_spinner=False)
def load_autos_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    for c in ["Modell", "Ausstattungslinie", "Motor", "Getriebe"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    if "Leistung" in df.columns:
        df["Leistung"] = pd.to_numeric(df["Leistung"], errors="coerce")
    return df

@st.cache_data(show_spinner=False)
def load_leasing_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    for c in ["Bedingung"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    for num in ["Laufzeit", "Freikilometer", "Leasingrate", "Tankguthaben"]:
        if num in df.columns:
            df[num] = pd.to_numeric(df[num], errors="coerce")
    return df

# --------------------------
# Helfer
# --------------------------

def infer_bedingung(modell: str, motor: str) -> str:
    name = (modell or "").lower()
    m = (motor or "").lower()
    if "caddy" in name:
        return "Caddy"
    if "multivan" in name:
        return "Multivan"
    e_markers = ["elektro", "ev", "bev", "phev", "plugin", "plug-in", "e-hybrid", "hybrid", "gte"]
    if any(tok in m for tok in e_markers):
        return "Elektro/Hybrid"
    return "Verbrenner"


def leasing_options_for(modell: str, motor: str, leasing_df: pd.DataFrame) -> pd.DataFrame:
    cond = infer_bedingung(modell, motor)
    sub = leasing_df[leasing_df["Bedingung"].str.lower() == cond.lower()]
    if sub.empty and cond in ("Caddy", "Multivan"):
        cond2 = infer_bedingung("", motor)
        sub = leasing_df[leasing_df["Bedingung"].str.lower() == cond2.lower()]
    return sub.sort_values(["Laufzeit", "Freikilometer"]).reset_index(drop=True)


def monthly_distance(km_per_year: int) -> float:
    return float(km_per_year) / 12.0


def monthly_consumption_cost(fuel_kind: str, l_per_100: float, kwh_per_100: float, prices: Dict[str, float], km_per_year: int) -> float:
    km_m = monthly_distance(km_per_year)
    cost = 0.0
    if l_per_100 and l_per_100 > 0:
        fk = fuel_kind if fuel_kind in ("Super E5", "Super E10", "Super+", "Diesel") else "Super E5"
        pl = float(prices.get(fk, 0))
        cost += (km_m * l_per_100 / 100.0) * pl
    if kwh_per_100 and kwh_per_100 > 0:
        pk = float(prices.get("Strom", 0))
        cost += (km_m * kwh_per_100 / 100.0) * pk
    return cost

# --------------------------
# Kopf + Energiepreise
# --------------------------
st.title("🚗 Mitarbeiter-Leasingrechner")

cols = st.columns(5)
if "energy_prices" not in st.session_state:
    st.session_state.energy_prices = DEFAULT_PRICES.copy()
ep = st.session_state.energy_prices
ep["Super E5"] = cols[0].number_input("Super E5 €/l", 0.5, 4.0, ep["Super E5"], 0.01)
ep["Super E10"] = cols[1].number_input("Super E10 €/l", 0.5, 4.0, ep["Super E10"], 0.01)
ep["Super+"] = cols[2].number_input("Super+ €/l", 0.5, 4.0, ep["Super+"], 0.01)
ep["Diesel"] = cols[3].number_input("Diesel €/l", 0.5, 4.0, ep["Diesel"], 0.01)
ep["Strom"] = cols[4].number_input("Strom €/kWh", 0.05, 2.0, ep["Strom"], 0.01)

# --------------------------
# Datenquellen
# --------------------------
autos_df = load_autos_csv("./autos.csv")
leasing_df = load_leasing_csv("./leasing.csv")
MODELS = sorted(autos_df["Modell"].dropna().unique().tolist())

# --------------------------
# Fahrzeug-Slot (kompaktes Layout)
# --------------------------

def render_car_slot(slot_idx: int, container):
    key = f"car{slot_idx}_"
    with container:
        st.markdown(f"**{slot_idx}. Auto**")
        model = st.selectbox("Modell", [""] + MODELS, key=key+"modell")
        if not model:
            return False, {}
        df_m = autos_df[autos_df["Modell"] == model]
        variants = sorted(df_m["Ausstattungslinie"].dropna().unique().tolist())
        variant = st.selectbox("Ausstattung", [""] + variants, key=key+"var")
        if not variant:
            return False, {}
        df_mv = df_m[df_m["Ausstattungslinie"] == variant]

        engines = sorted(df_mv["Motor"].dropna().unique().tolist())
        engine = st.selectbox("Motor", [""] + engines, key=key+"engine")
        if not engine:
            return False, {}
        df_mve = df_mv[df_mv["Motor"] == engine]

        leistungen = sorted(df_mve["Leistung"].dropna().unique().tolist())
        leistung = st.selectbox("Leistung (kW)", [""] + [int(x) for x in leistungen], key=key+"kw")
        if not leistung:
            return False, {}

        getriebe_opts = sorted(df_mve[df_mve["Leistung"] == int(leistung)]["Getriebe"].dropna().unique().tolist())
        getriebe = st.selectbox("Getriebe", [""] + getriebe_opts, key=key+"gear")
        if not getriebe:
            return False, {}

        leas_df = leasing_options_for(model, engine, leasing_df)
        if leas_df.empty:
            st.warning("Keine Leasingoptionen")
            return False, {}
        rate_values = sorted(leas_df["Leasingrate"].dropna().unique().tolist())
        rate = st.selectbox("Leasingrate %", rate_values, key=key+"rate")

        row_rate = leas_df[leas_df["Leasingrate"] == float(rate)].iloc[0]
        laufzeit = int(row_rate["Laufzeit"])
        default_km = int(row_rate["Freikilometer"])
        tankguthaben = float(row_rate["Tankguthaben"])

        km_year = st.number_input("Freikilometer/Jahr", 0, 100000, default_km, 1000, key=key+"km")
        uvp = st.number_input("UVP €", 1000, 300000, 30000, 500, key=key+"uvp")
        fuel_kind = st.selectbox("Kraftstoff", ["Super E5", "Super E10", "Super+", "Diesel", "Elektro", "Hybrid"], key=key+"fuel")

        l100, kwh100 = 0.0, 0.0
        if fuel_kind == "Elektro":
            kwh100 = st.number_input("kWh/100 km", 5.0, 40.0, 16.0, 0.1, key=key+"kwh")
        elif fuel_kind == "Hybrid":
            l100 = st.number_input("l/100 km", 0.0, 30.0, 1.0, 0.1, key=key+"l100")
            kwh100 = st.number_input("kWh/100 km", 0.0, 40.0, 12.0, 0.1, key=key+"kwh")
        else:
            l100 = st.number_input("l/100 km", 0.5, 30.0, 5.5, 0.1, key=key+"l100")

        lease_monthly = uvp * (float(rate) / 100.0)
        fuel_cost_m = monthly_consumption_cost(fuel_kind, l100, kwh100, st.session_state.energy_prices, int(km_year))
        fuel_cost_net = max(0.0, fuel_cost_m - tankguthaben)

        result = {
            "slot": slot_idx,
            "Modell": model,
            "Ausstattungslinie": variant,
            "Motor": engine,
            "Leistung": int(leistung),
            "Getriebe": getriebe,
            "UVP": uvp,
            "lease_percent": float(rate),
            "km_year": km_year,
            "laufzeit": laufzeit,
            "tankguthaben": tankguthaben,
            "fuel_kind": fuel_kind,
            "l_per_100": l100,
            "kwh_per_100": kwh100,
            "monthly_fees_only": lease_monthly,
            "monthly_with_consumption": lease_monthly + fuel_cost_net,
            "total_fees_only": lease_monthly * laufzeit,
            "total_with_consumption": (lease_monthly + fuel_cost_net) * laufzeit,
        }
        return True, result

# --------------------------
# Autos in Reihen von 5
# --------------------------
results: List[dict] = []
num_slots = MAX_CARS

row1 = st.columns(5)
row2 = st.columns(5)

# Erste Reihe
row1_completed = True
for i in range(5):
    completed, res = render_car_slot(i+1, row1[i])
    if res:
        results.append(res)
    row1_completed = row1_completed and completed

# Zweite Reihe nur, wenn erste komplett
if row1_completed:
    for i in range(5):
        completed, res = render_car_slot(i+6, row2[i])
        if res:
            results.append(res)

# --------------------------
# Rankings
# --------------------------
if results:
    st.subheader("Ranking – Nur Gebühren")
    fees_df = pd.DataFrame([{
        "#": r["slot"],
        "Modell": f"{r['Modell']} {r['Ausstattungslinie']} ({r['Motor']}, {r['Leistung']} kW, {r['Getriebe']})",
        "UVP €": r["UVP"],
        "Leasing %": r["lease_percent"],
        "Monat Gebühren €": r["monthly_fees_only"],
        "Gesamt € (nur Gebühren)": r["total_fees_only"],
    } for r in results]).sort_values(["Monat Gebühren €", "UVP €"]).reset_index(drop=True)
    st.dataframe(fees_df, use_container_width=True)

    st.subheader("Ranking – Inkl. Verbrauch")
    with_df = pd.DataFrame([{
        "#": r["slot"],
        "Modell": f"{r['Modell']} {r['Ausstattungslinie']} ({r['Motor']}, {r['Leistung']} kW, {r['Getriebe']})",
        "UVP €": r["UVP"],
        "Leasing %": r["lease_percent"],
        "Tankguthaben €/Monat": r["tankguthaben"],
        "Monat inkl. Verbrauch €": r["monthly_with_consumption"],
        "Gesamt € (inkl. Verbrauch)": r["total_with_consumption"],
    } for r in results]).sort_values(["Monat inkl. Verbrauch €", "UVP €"]).reset_index(drop=True)
    st.dataframe(with_df, use_container_width=True)
else:
    st.info("Bitte Autos auswählen, um Ranking zu sehen.")
