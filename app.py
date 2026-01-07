import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Momentum v12", layout="wide")
st.title("🚀 Dashboard Momentum: RSI & MACD Breakout")

# --- 1. FITUR FETCH DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Buffer 1 tahun untuk hitung indikator teknikal (RSI & MACD butuh histori)
    extended_start = start_date - timedelta(days=365)
    try:
        df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume']
    except:
        return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=86400)
def get_free_float(ticker_jk):
    try:
        info = yf.Ticker(ticker_jk).info
        f_shares = info.get('floatShares')
        total_s = info.get('sharesOutstanding')
        if f_shares and total_s: return (f_shares / total_s) * 100
    except: pass
    return None

# --- 2. LOAD DATABASE EMITEN ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

df_emiten, _ = load_data_auto()

# --- 3. LOGIKA ANALISA (MOMENTUM & TREND) ---
def get_signals_and_data(df_c, df_v, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    
    for col in df_c.columns:
        # Pembersihan data
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        
        if len(c) < 30: continue # Butuh minimal data untuk RSI/MACD
        
        # --- INDIKATOR TEKNIKAL ---
        # 1. RSI (Periode 14)
        rsi = ta.rsi(c, length=14)
        rsi_last = rsi.iloc[-1] if rsi is not None else 50
        
        # 2. MACD (12, 26, 9)
        macd_df = ta.macd(c, fast=12, slow=26, signal=9)
        macd_val = macd_df['MACD_12_26_9'].iloc[-1]
        macd_sig = macd_df['MACDs_12_26_9'].iloc[-1]
        macd_hist = macd_df['MACDh_12_26_9'].iloc[-1]
        
        # 3. Volume & Price Action
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma20 if v_sma20 > 0 else 0
        
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        ticker = str(col).replace('.JK','')
        
        # --- FILTER SHORTLIST (TARGET < 2 MINGGU) ---
        # Syarat 1: RSI sedang menanjak (bukan jenuh beli, tapi kuat)
        is_rsi_strong = 45 < rsi_last < 75
        
        # Syarat 2: MACD Golden Cross atau Bullish Histogram
        is_macd_bullish = macd_hist > 0 and macd_val > macd_sig
        
        # Syarat 3: Volume Explosion (Bandar Masuk)
        is_vol_spike = v_ratio > 1.8 
        
        # Syarat 4: Price Movement (Mulai Breakout)
        is_breakout = 0.01 < chg_5d < 0.07 

        status = "Netral"
        if is_analisa_lengkap:
            is_liquid = (v_last / 100) > 500
            
            if is_rsi_strong and is_macd_bullish and is_vol_spike and is_liquid:
                status = "🔥 STRONG BUY"
                shortlist_keys.append(ticker)
            elif is_macd_bullish:
                status = "⤴️ Bullish Turn"
            elif rsi_last > 70:
                status = "⚠️ Overbought"
        
        results.append({
            'Kode Saham': ticker,
            'Status': status,
            'RSI (14)': f"{rsi_last:.1f}",
            'MACD Hist': f"{macd_hist:.2f}",
            'Vol Ratio (SMA20)': f"{v_ratio:.2f}x",
            'Chg 5D (%)': f"{chg_5d*100:.1f}%",
            'Last Price': f"{int(c.iloc[-1])}"
        })
        
    return pd.DataFrame(results), shortlist_keys

# --- 4. RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Pantau Saham Tertentu:", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=5000)
    start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=20))
    end_d = st.sidebar.date_input("Akhir", date.today())

    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa Momentum")

    if btn_analisa:
        with st.spinner('Menghitung RSI & MACD...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c_raw.empty:
                # Handling MultiIndex Columns
                if isinstance(df_c_raw.columns, pd.MultiIndex):
                    df_c_raw.columns = df_c_raw.columns.get_level_values(1)
                    df_v_raw.columns = df_v_raw.columns.get_level_values(1)

                # Filter Harga & Likuiditas
                last_prices = df_c_raw.ffill().iloc[-1]
                saham_lolos = last_prices[(last_prices >= min_p) & (last_prices <= max_p)].index
                
                df_analysis, shortlist_keys = get_signals_and_data(df_c_raw[saham_lolos], df_v_raw[saham_lolos], is_analisa_lengkap=True)

                # TAMPILKAN SHORTLIST
                st.subheader("🎯 Momentum Shortlist (Potensi Naik < 2 Minggu)")
                st.write("Kriteria: RSI Kuat, MACD Bullish, & Volume Explosion.")
                
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
                if not df_top.empty:
                    st.dataframe(df_top.style.background_gradient(cmap='RdYlGn', subset=['RSI (14)']), use_container_width=True)
                else:
                    st.info("Belum ada saham yang memenuhi kriteria ledakan momentum.")

                st.divider()
                st.subheader("📊 Seluruh Hasil Analisa")
                st.dataframe(df_analysis, use_container_width=True)
else:
    st.error("File database 'Kode Saham.xlsx' tidak ditemukan.")
