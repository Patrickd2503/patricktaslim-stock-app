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

st.markdown("""
**Update v13 + Visual Analysis:**
- ✅ **Chart Recommendation** 🆕: Deteksi otomatis High Risk (Illiquid/Patah) & Overextended.
- ✅ ADX pakai **DI+ vs DI-** (arah tren benar-benar bullish)
- ✅ **Bearish Divergence** otomatis tolak dari Shortlist
- ✅ ADX Trend **Falling** tidak masuk shortlist
- ✅ Relative Volume dibandingkan **50D** juga
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
        return "❌ High Risk", "Chart patah-patah/tidak likuid (Hati-hati!)."
    elif dist_ma20 > 15:
        return "⚠️ Overextended", f"Sudah naik terlalu jauh dari MA20 (+{dist_ma20:.1f}%)."
    elif last_p > ma20:
        return "✅ Healthy", "Struktur chart rapi & uptrend."
    else:
        return "➡️ Neutral", "Chart konsolidasi atau sideways."

# ─────────────────────────────────────────────
# 2. CACHE DATA (v13 Original)
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=500)
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        return df
    except Exception as e:
        st.error(f"Error download data: {e}")
        return None

# ─────────────────────────────────────────────
# 3. LOAD DATABASE EMITEN
# ─────────────────────────────────────────────
def load_emiten():
    if os.path.exists('FreeFloat.xlsx'):
        try:
            df = pd.read_excel('FreeFloat.xlsx')
            df.columns = df.columns.str.strip()
            df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK','',regex=False)
            if 'Free Float' in df.columns:
                df['Free Float'] = pd.to_numeric(df['Free Float'], errors='coerce').fillna(0)
                if df['Free Float'].max() <= 1.0:
                    df['Free Float'] = df['Free Float'] * 100
            else:
                df['Free Float'] = 0
            return df, "FreeFloat.xlsx"
        except Exception as e:
            st.error(f"Error membaca file Excel: {e}")
    
    # Default jika file tidak ada
    return pd.DataFrame({'Kode Saham': ['BBCA','BBRI','TLKM','ASII','BUKA','KPIG'], 'Free Float': [0]*6}), "Default (No File)"

df_emiten, loaded_file = load_emiten()

# ─────────────────────────────────────────────
# 4. SIDEBAR (v13 Original)
# ─────────────────────────────────────────────
st.sidebar.header("📊 Filter Screener")
min_p = st.sidebar.number_input("Harga Minimal", value=50)
max_ff = st.sidebar.slider("Max Free Float (%)", 0.0, 100.0, 100.0)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=10000)
exclude_falling_adx = st.sidebar.checkbox("Exclude Falling ADX Trend", value=True)
exclude_dist = st.sidebar.checkbox("Exclude Distribusi (PVA)", value=True)

if st.sidebar.button("🕵️ JALANKAN MONITOR v13"):
    with st.spinner("Sedang menganalisa seluruh emiten..."):
        ticker_list = [t + ".JK" for t in df_emiten['Kode Saham'].tolist()]
        raw_data = fetch_yf_all_data(ticker_list, date.today() - timedelta(days=60), date.today())
        
        if raw_data is not None and not raw_data.empty:
            results = []
            
            # Ambil IHSG untuk RS
            try:
                jkse_c = raw_data['Close']['^JKSE'].dropna()
            except:
                jkse_c = None

            for t_code in df_emiten['Kode Saham'].tolist():
                try:
                    symbol = t_code + ".JK"
                    # Ambil data per kolom (handling MultiIndex yfinance)
                    c = raw_data['Close'][symbol].dropna()
                    h = raw_data['High'][symbol].dropna()
                    l = raw_data['Low'][symbol].dropna()
                    v = raw_data['Volume'][symbol].dropna()
                    
                    if len(c) < 60: continue
                    
                    # 1. ANALISA TEKNIKAL v13 (ADX & MFI)
                    adx_df = pta.adx(h, l, c, length=14)
                    adx_val = adx_df['ADX_14'].iloc[-1]
                    dmp = adx_df['DMP_14'].iloc[-1]
                    dmn = adx_df['DMN_14'].iloc[-1]
                    adx_trend = "Rising" if adx_val > adx_df['ADX_14'].iloc[-2] else "Falling"
                    
                    mfi_val = pta.mfi(h, l, c, v, length=14).iloc[-1]
                    
                    # 2. NEW: ANALISA CHART VISUAL
                    chart_rec, chart_note = analyze_chart_visual(c, h, l)

                    # 3. FILTER v13
                    if exclude_falling_adx and adx_trend == "Falling": continue
                    if dmp < dmn: continue # Hanya yang Bullish (DI+ > DI-)
                    
                    # Cek Bearish Divergence (v13)
                    is_bear_div = (c.iloc[-1] > c.iloc[-10:-1].max()) and (mfi_val < pta.mfi(h, l, c, v, length=14).iloc[-10:-1].max())
                    if is_bear_div: continue

                    # 4. KUMPULKAN HASIL
                    results.append({
                        'Kode': t_code,
                        'Chart Rec': chart_rec, # KOLOM BARU
                        'Price': int(c.iloc[-1]),
                        'ADX': round(adx_val, 1),
                        'ADX Trend': adx_trend,
                        'MFI': round(mfi_val, 1),
                        'RelVol 50D': round(v.iloc[-1] / v.rolling(50).mean().iloc[-1], 2),
                        'Chart Note': chart_note # KOLOM BARU
                    })
                except:
                    continue
            
            if results:
                st.subheader(f"✅ Shortlist v13 - {date.today()}")
                df_res = pd.DataFrame(results).sort_values('ADX', ascending=False)
                
                # Styling
                def style_chart(val):
                    color = 'red' if '❌' in str(val) or '⚠️' in str(val) else ('green' if '✅' in str(val) else 'gray')
                    return f'color: {color}; font-weight: bold'

                st.dataframe(df_res.style.applymap(style_chart, subset=['Chart Rec']), use_container_width=True)
            else:
                st.info("Tidak ada saham yang lolos kriteria v13 saat ini.")
        else:
            st.error("Gagal menarik data dari Yahoo Finance.")

else:
    st.info(f"📂 Database: **{loaded_file}** | Silakan klik tombol di sidebar untuk mulai.")
