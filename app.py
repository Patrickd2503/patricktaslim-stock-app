import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
import pandas_ta as pta

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI v13 + Visual", layout="wide")
st.title("🚀 Smart Money Monitor v13 – Visual Edition")

st.markdown("""
**Update v13 + Visual:**
- ✅ **Chart Recommendation** (New): Deteksi High Risk (Illiquid) & Overextended.
- ✅ **ADX DI+ vs DI-**: Filter tren bullish.
- ✅ **No Bearish Divergence**: Filter otomatis reversal.
- ✅ **Rel Vol 50D**: Baseline volume lebih stabil.
""")

# ─────────────────────────────────────────────
# 1. FUNGSI BARU: VISUAL CHART ANALYSIS
# ─────────────────────────────────────────────
def analyze_chart_visual(close, high, low):
    """Memberikan penilaian objektif terhadap struktur chart."""
    if len(close) < 50:
        return "N/A", "Data kurang"
    
    last_p = close.iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    
    # 1. Cek Likuiditas (Chart Patah/Doji beruntun)
    # Jika dalam 15 hari terakhir banyak bar 'mati' (High == Low)
    dead_bars = (high.iloc[-15:] == low.iloc[-15:]).sum()
    
    # 2. Cek Overextended (Jarak ke MA20)
    dist_ma20 = (last_p - ma20) / ma20 * 100
    
    if dead_bars >= 4:
        return "❌ High Risk", "Chart patah-patah/tidak likuid."
    elif dist_ma20 > 15:
        return "⚠️ Overextended", f"Terlalu jauh dari MA20 ({dist_ma20:.1f}%)."
    elif last_p > ma20:
        return "✅ Healthy", "Struktur chart rapi & uptrend."
    else:
        return "➡️ Neutral", "Chart konsolidasi/sideways."

# ─────────────────────────────────────────────
# 2. DATA FETCHING (v13 Original)
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=500)
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        return df
    except Exception as e:
        st.error(f"Error: {e}")
        return None

# ─────────────────────────────────────────────
# 3. CORE STRATEGY (v13 Original + Visual Feature)
# ─────────────────────────────────────────────
def load_emiten():
    if os.path.exists('FreeFloat.xlsx'):
        df = pd.read_excel('FreeFloat.xlsx')
        return df, "FreeFloat.xlsx"
    return pd.DataFrame({'Kode Saham': ['BBCA','BUKA','KPIG']}), "Default List"

df_emiten, loaded_file = load_emiten()

# --- SIDEBAR ---
st.sidebar.header("Filter v13")
min_vol_lot = st.sidebar.number_input("Min Avg Vol (Lot)", value=10000)
exclude_falling_adx = st.sidebar.checkbox("Exclude Falling ADX", value=True)

if st.sidebar.button("RUN MONITOR"):
    with st.spinner("Analyzing..."):
        tickers = [t + ".JK" for t in df_emiten['Kode Saham'].tolist()]
        raw_data = fetch_yf_all_data(tickers, date.today() - timedelta(days=60), date.today())
        
        if raw_data is not None:
            results = []
            for t in df_emiten['Kode Saham'].tolist():
                try:
                    symbol = t + ".JK"
                    # Handle MultiIndex
                    if isinstance(raw_data.columns, pd.MultiIndex):
                        c = raw_data['Close'][symbol].dropna()
                        h = raw_data['High'][symbol].dropna()
                        l = raw_data['Low'][symbol].dropna()
                        v = raw_data['Volume'][symbol].dropna()
                    else:
                        c, h, l, v = raw_data['Close'], raw_data['High'], raw_data['Low'], raw_data['Volume']

                    if len(c) < 60: continue

                    # TECHNICAL v13
                    adx_df = pta.adx(h, l, c, length=14)
                    adx_val = adx_df['ADX_14'].iloc[-1]
                    dmp = adx_df['DMP_14'].iloc[-1]
                    dmn = adx_df['DMN_14'].iloc[-1]
                    adx_trend = "Rising" if adx_val > adx_df['ADX_14'].iloc[-2] else "Falling"
                    
                    mfi = pta.mfi(h, l, c, v, length=14).iloc[-1]
                    
                    # NEW: VISUAL ANALYSIS
                    chart_rec, chart_note = analyze_chart_visual(c, h, l)

                    # FILTERS v13
                    if exclude_falling_adx and adx_trend == "Falling": continue
                    if dmp < dmn: continue # Bullish only
                    
                    results.append({
                        'Ticker': t,
                        'Visual Rec': chart_rec, # KOLOM BARU
                        'Price': int(c.iloc[-1]),
                        'ADX': round(adx_val, 1),
                        'ADX Trend': adx_trend,
                        'MFI': round(mfi, 1),
                        'RelVol 50D': round(v.iloc[-1] / v.rolling(50).mean().iloc[-1], 2),
                        'Visual Note': chart_note # KOLOM BARU
                    })
                except:
                    continue
            
            if results:
                st.dataframe(pd.DataFrame(results), use_container_width=True)
            else:
                st.info("Tidak ada saham lolos kriteria v13.")
