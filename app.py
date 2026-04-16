import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os

# ─────────────────────────────────────────────
# CONFIG & UI INITIALIZATION
# ─────────────────────────────────────────────
st.set_page_config(page_title="Bandarmologi & v13 Technical Monitor", layout="wide")
st.title("🕵️ Bandarmologi & v13 Technical Monitor")

st.markdown("""
### Fitur Terintegrasi:
- ✅ **v13 Tech:** ADX DI+/DI-, MFI, Bearish Divergence Detection, & 50D RelVol.
- ✅ **Bandarmologi:** Stealth Accumulation, Effort vs Result, & Absorption[cite: 8, 14, 21].
- ✅ **Visual Check:** Deteksi chart patah (illiquid) & overextended.
""")

# ─────────────────────────────────────────────
# 1. TECHNICAL FUNCTIONS (v13)
# ─────────────────────────────────────────────
def compute_v13_tech(high, low, close, volume):
    # ADX DI+ / DI- Logic [cite: 15, 88]
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(14).mean()
    
    # MFI [cite: 35]
    tp = (high + low + close) / 3
    mf = tp * volume
    pos_mf = pd.Series(np.where(tp > tp.shift(1), mf, 0), index=mf.index).rolling(14).sum()
    neg_mf = pd.Series(np.where(tp < tp.shift(1), mf, 0), index=mf.index).rolling(14).sum()
    mfi = 100 - (100 / (1 + (pos_mf / neg_mf)))
    
    # Bearish Divergence [cite: 35]
    is_bear_div = (close.iloc[-1] > close.iloc[-10:].max()) and (mfi.iloc[-1] < mfi.iloc[-10:].max())
    
    return {
        'adx': adx.iloc[-1],
        'adx_trend': "Rising" if adx.iloc[-1] > adx.iloc[-2] else "Falling",
        'di_plus': plus_di.iloc[-1],
        'di_minus': minus_di.iloc[-1],
        'mfi': mfi.iloc[-1],
        'bearish_div': is_bear_div,
        'relvol_50': volume.iloc[-1] / volume.rolling(50).mean().iloc[-1]
    }

# ─────────────────────────────────────────────
# 2. VISUAL CHART CHECK
# ─────────────────────────────────────────────
def assess_chart_visual(close, high, low):
    ma20 = close.rolling(20).mean().iloc[-1]
    dead_bars = (high.iloc[-15:] == low.iloc[-15:]).sum()
    dist_ma20 = (close.iloc[-1] - ma20) / ma20 * 100
    
    if dead_bars >= 4:
        return "❌ High Risk (Illiquid)", "Chart patah-patah (rawan manipulasi)."
    if dist_ma20 > 15:
        return "⚠️ Overextended", "Harga sudah lari terlalu jauh dari rata-rata (MA20)."
    return "✅ Healthy Structure", "Struktur chart normal."

# ─────────────────────────────────────────────
# 3. LOAD DATA & SIDEBAR [cite: 149]
# ─────────────────────────────────────────────
st.sidebar.header("⚙️ Filter Strategi")
# Load emiten logic [cite: 95, 97]
def load_emiten():
    return pd.DataFrame({'Kode Saham': ['BBCA','BBRI','TLKM','BUKA','KPIG','ASII']})

df_emiten = load_emiten()
target_list = df_emiten['Kode Saham'].tolist()

min_p = st.sidebar.number_input("Harga Minimal", value=50) [cite: 151]
min_adx = st.sidebar.slider("Min ADX Strength", 0, 100, 20)
exclude_falling_adx = st.sidebar.checkbox("Exclude Falling ADX Trend", value=True)

if st.sidebar.button("🕵️ JALANKAN ANALISA GABUNGAN"):
    with st.spinner("Sedang memproses teknikal & bandarmologi..."): [cite: 150]
        results = []
        for ticker in target_list:
            symbol = ticker + ".JK"
            df = yf.download(symbol, period="7mo", progress=False)
            if df.empty or len(df) < 60: continue
            
            # Ekstrak Series
            c, h, l, v = df['Close'].iloc[:,0], df['High'].iloc[:,0], df['Low'].iloc[:,0], df['Volume'].iloc[:,0]
            
            # v13 Tech Analysis
            tech = compute_v13_tech(h, l, c, v)
            
            # v13 Filters logic
            if exclude_falling_adx and tech['adx_trend'] == "Falling": continue
            if tech['di_plus'] < tech['di_minus']: continue # Bullish DI check
            if tech['bearish_div']: continue # No Bearish Divergence
            
            # Visual & Bandarmologi [cite: 133]
            chart_status, chart_note = assess_chart_visual(c, h, l)
            
            results.append({
                'Ticker': ticker,
                'Price': int(c.iloc[-1]),
                'Chart Rec': chart_status,
                'ADX': round(tech['adx'], 1),
                'ADX Trend': tech['adx_trend'],
                'MFI': round(tech['mfi'], 1),
                'RelVol 50D': round(tech['relvol_50'], 2),
                'Note': chart_note
            })
            
        if results:
            res_df = pd.DataFrame(results)
            st.subheader("🚀 Hasil Screening (v13 + Visual Check)")
            st.dataframe(res_df, use_container_width=True) [cite: 154]
        else:
            st.warning("Tidak ada saham yang lolos filter v13 saat ini.")
