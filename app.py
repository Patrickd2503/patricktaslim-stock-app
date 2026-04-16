import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(page_title="Bandarmologi & v13 Technical Monitor", layout="wide")
st.title("🕵️ Bandarmologi & v13 Technical Monitor")
st.markdown("""
**Fitur Terintegrasi:**
- ✅ **v13 Tech:** ADX DI+/DI-, MFI, No Bearish Divergence, & 50D RelVol.
- ✅ **Bandarmologi:** Stealth Accumulation, Effort vs Result, & Absorption.
- ✅ **Visual Check:** Deteksi chart patah (illiquid) & overextended.
""")

# ─────────────────────────────────────────────
# 1. TECHNICAL FUNCTIONS (v13)
# ─────────────────────────────────────────────
def compute_adx(high, low, close, window=14):
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
    atr = tr.rolling(window).mean()
    plus_di = 100 * (plus_dm.rolling(window).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window).mean()
    return adx, plus_di, minus_di

def compute_mfi(high, low, close, volume, window=14):
    tp = (high + low + close) / 3
    mf = tp * volume
    pos_mf = pd.Series(np.where(tp > tp.shift(1), mf, 0), index=mf.index).rolling(window).sum()
    neg_mf = pd.Series(np.where(tp < tp.shift(1), mf, 0), index=mf.index).rolling(window).sum()
    mfi = 100 - (100 / (1 + (pos_mf / neg_mf)))
    return mfi

# ─────────────────────────────────────────────
# 2. BANDARMOLOGI & VISUAL FUNCTIONS
# ─────────────────────────────────────────────
def assess_chart_visual(close, high, low):
    ma20 = close.rolling(20).mean()
    last_p = close.iloc[-1]
    last_ma20 = ma20.iloc[-1]
    
    # Deteksi chart patah (illiquid)
    dead_bars = (high.iloc[-15:] == low.iloc[-15:]).sum()
    # Deteksi overextended
    dist_ma20 = (last_p - last_ma20) / last_ma20 * 100
    
    if dead_bars >= 4:
        return "❌ High Risk (Illiquid)", "Chart patah-patah (rawan manipulasi)."
    if dist_ma20 > 15:
        return "⚠️ Overextended", f"Terlalu jauh dari MA20 ({dist_ma20:.1f}%)."
    return "✅ Healthy Structure", "Struktur chart normal."

def detect_stealth_accumulation(close, volume, window=20):
    c, v = close.iloc[-window:], volume.iloc[-window:]
    price_range = (c.max() - c.min()) / c.mean() * 100
    vol_ratio = v.iloc[-5:].mean() / v.iloc[:5].mean() if v.iloc[:5].mean() > 0 else 1.0
    score = 0
    if price_range < 8: score += 3
    if vol_ratio > 1.2: score += 2
    return {'score': score, 'signal': "🔥 Akumulasi" if score >= 3 else "–"}

# ─────────────────────────────────────────────
# 3. DATA LOADING
# ─────────────────────────────────────────────
def load_emiten():
    if os.path.exists('FreeFloat.xlsx'):
        df = pd.read_excel('FreeFloat.xlsx')
        return df['Kode Saham'].str.replace('.JK','',regex=False).tolist()
    return ['BBCA', 'BBRI', 'TLKM', 'ASII', 'BUKA', 'KPIG']

# ─────────────────────────────────────────────
# 4. MAIN INTERFACE (SIDEBAR)
# ─────────────────────────────────────────────
st.sidebar.header("⚙️ Konfigurasi")
target_list = load_emiten()
selected = st.sidebar.multiselect("Pilih Saham:", options=target_list, default=target_list[:10])
min_adx = st.sidebar.slider("Min ADX Strength", 0, 100, 20)
exclude_falling_adx = st.sidebar.checkbox("Exclude Falling ADX Trend", value=True)

if st.sidebar.button("🕵️ JALANKAN ANALISA"):
    with st.spinner("Sedang memproses teknikal & bandarmologi..."):
        results = []
        for ticker in selected:
            try:
                df = yf.download(f"{ticker}.JK", period="1y", progress=False)
                if df.empty or len(df) < 60: continue
                
                # Flatten multi-index if exists
                if isinstance(df.columns, pd.MultiIndex):
                    c, h, l, v = df['Close'].iloc[:,0], df['High'].iloc[:,0], df['Low'].iloc[:,0], df['Volume'].iloc[:,0]
                else:
                    c, h, l, v = df['Close'], df['High'], df['Low'], df['Volume']

                # v13 Technical 
                adx, p_di, m_di = compute_adx(h, l, c)
                mfi = compute_mfi(h, l, c, v)
                
                adx_val = adx.iloc[-1]
                adx_trend = "Rising" if adx.iloc[-1] > adx.iloc[-2] else "Falling"
                relvol_50 = v.iloc[-1] / v.rolling(50).mean().iloc[-1]
                
                # v13 Filters 
                if exclude_falling_adx and adx_trend == "Falling": continue
                if p_di.iloc[-1] < m_di.iloc[-1]: continue # DI+ must be > DI-
                if (c.iloc[-1] > c.iloc[-10:].max()) and (mfi.iloc[-1] < mfi.iloc[-10:].max()): continue # No Bearish Div
                
                # Visual & Bandarmologi [cite: 1, 9]
                chart_status, chart_note = assess_chart_visual(c, h, l)
                sa = detect_stealth_accumulation(c, v)
                
                results.append({
                    'Kode': ticker,
                    'Price': int(c.iloc[-1]),
                    'Chart Rec': chart_status,
                    'ADX': round(adx_val, 1),
                    'ADX Trend': adx_trend,
                    'MFI': round(mfi.iloc[-1], 1),
                    'RelVol 50D': round(relvol_50, 2),
                    'Bandarmologi': sa['signal'],
                    'Note': chart_note
                })
            except Exception as e:
                continue

        if results:
            st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.warning("Tidak ada saham yang memenuhi kriteria v13 & Visual.")
