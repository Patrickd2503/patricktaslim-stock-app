import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO
import pandas_ta as pta

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI v13", layout="wide")
st.title("🚀 Dashboard Akumulasi: Smart Money Monitor v13 – Precision Edition")

# ─────────────────────────────────────────────
# 🆕 0. FUNGSI ANALISA CHART (TAMBAHAN)
# ─────────────────────────────────────────────
def analyze_chart_condition(close: pd.Series, high: pd.Series, low: pd.Series):
    if len(close) < 30:
        return "Data Kurang"

    last_price = close.iloc[-1]

    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]

    high_20 = high.rolling(20).max().iloc[-1]
    low_20  = low.rolling(20).min().iloc[-1]

    dist_ma20 = (last_price - ma20) / ma20 * 100 if ma20 > 0 else 0

    if last_price >= high_20 * 0.99:
        if dist_ma20 > 15:
            return "Overextended 🚨"
        return "Breakout Valid 🚀"

    if last_price > ma20 and last_price > ma50:
        if dist_ma20 < 5:
            return "Pullback Healthy 👍"
        return "Uptrend Normal"

    if last_price < ma20 and last_price < ma50:
        return "Downtrend ❌"

    return "Sideways / Konsolidasi"

# ─────────────────────────────────────────────
# 1. CACHE DATA
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=500)
    df = yf.download(all_tickers, start=extended_start, end=end_date,
                     threads=True, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        return df['Close'], df['Volume'], df['High'], df['Low']
    else:
        return df[['Close']], df[['Volume']], df[['High']], df[['Low']]

# ─────────────────────────────────────────────
# 2. LOAD DATABASE
# ─────────────────────────────────────────────
def load_data_auto():
    file_name = 'FreeFloat.xlsx'
    if os.path.exists(file_name):
        df = pd.read_excel(file_name)
        df.columns = df.columns.str.strip()
        df['Kode Saham'] = df['Kode Saham'].str.upper().str.replace('.JK', '', regex=False)
        return df, file_name

    return pd.DataFrame({'Kode Saham':['WINS'],'Free Float':[30]}), "Default"

df_emiten, loaded_file = load_data_auto()

# ─────────────────────────────────────────────
# 3. ANALISA UTAMA (MODIFIED)
# ─────────────────────────────────────────────
def get_signals_and_data(df_c, df_v, df_h, df_l, df_ref, min_vol_lot):
    results = []

    for col in df_c.columns:
        if col == "^JKSE":
            continue

        c = df_c[col].dropna()
        v = df_v[col].dropna()
        h = df_h[col].dropna()
        l = df_l[col].dropna()

        if len(c) < 55:
            continue

        # 🆕 CHART ANALYSIS
        chart_analysis = analyze_chart_condition(c, h, l)

        avg_vol20 = v.rolling(20).mean().iloc[-1]
        rel_vol = v.iloc[-1] / avg_vol20 if avg_vol20 > 0 else 0

        ma20 = c.rolling(20).mean().iloc[-1]
        is_above_ma20 = "YA" if c.iloc[-1] > ma20 else "TIDAK"

        results.append({
            'Kode Saham': col.replace(".JK",""),
            'Last Price': int(c.iloc[-1]),
            'Rel Vol': round(rel_vol,2),
            'Above MA20': is_above_ma20,

            # ✅ KOLOM BARU
            'Chart Analysis': chart_analysis
        })

    return pd.DataFrame(results)

# ─────────────────────────────────────────────
# 4. UI
# ─────────────────────────────────────────────
st.sidebar.header("Setting")
min_vol = st.sidebar.number_input("Min Volume", value=100000)

if st.sidebar.button("Run"):
    tickers = df_emiten['Kode Saham'].tolist()
    tickers_jk = [t+".JK" for t in tickers]

    df_c, df_v, df_h, df_l = fetch_yf_all_data(tickers_jk, date.today()-timedelta(days=60), date.today())

    df = get_signals_and_data(df_c, df_v, df_h, df_l, df_emiten, min_vol)

    st.dataframe(df)
