import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Top Pick Momentum Monitor", layout="wide")
st.title("💎 Top Pick Momentum Screener")

# --- 1. FUNGSI FETCH HARGA TERAKHIR (CEPAT) ---
def get_current_prices(tickers):
    """Mengambil harga terakhir saja untuk filter awal agar cepat"""
    try:
        data = yf.download(tickers, period="1d", threads=True, progress=False)
        if data.empty: return pd.Series()
        return data['Close'].iloc[-1]
    except:
        return pd.Series()

# --- 2. FUNGSI FETCH DATA HISTORI (HANYA UNTUK YANG LOLOS FILTER) ---
@st.cache_data(ttl=3600)
def fetch_hist_data(tickers, start_date):
    extended_start = start_date - timedelta(days=365)
    try:
        df = yf.download(list(tickers), start=extended_start, threads=True, progress=False)
        if df.empty: return pd.DataFrame(), pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume']
        return df[['Close']], df[['Volume']]
    except:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. LOGIKA ANALISA (FIX VALUEERROR) ---
def get_signals(df_c, df_v):
    results, shortlist_keys = [], []
    if df_c.empty: return pd.DataFrame(), []

    for col in df_c.columns:
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        if len(c) < 35: continue 
        
        # Indikator
        rsi = ta.rsi(c, length=14)
        rsi_val = float(rsi.iloc[-1]) if rsi is not None and not rsi.empty else 50
        
        macd = ta.macd(c)
        # Fix ValueError: Pastikan mengambil angka tunggal (float)
        macd_h = float(macd.filter(like='MACDh').iloc[-1]) if macd is not None and not macd.empty else 0
        
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        price_last = float(c.iloc[-1])
        
        v_ratio = float(v_last / v_sma20) if v_sma20 > 0 else 0
        turnover = v_last * price_last
        
        # PARAMETER KETAT (Konversi ke boolean murni)
        is_strong_rsi = bool(55 < rsi_val < 70)
        is_bullish_macd = bool(macd_h > 0)
        is_above_ma20 = bool(price_last > ma20)
        is_ultra_vol = bool(v_ratio > 2.5)
        is_liquid = bool(turnover > 2_000_000_000)
        
        ticker = str(col).replace('.JK','')
        
        if is_strong_rsi and is_bullish_macd and is_above_ma20 and is_ultra_vol and is_liquid:
            status = "💎 TOP PICK"
            shortlist_keys.append(ticker)
        elif is_bullish_macd and is_above_ma20 and v_ratio > 1.2:
            status = "⚡ Momentum"
        else:
            status = "Wait & See"

        results.append({
            'Kode Saham': ticker,
            'Status': status,
            'Last Price': int(price_last),
            'Vol Ratio': round(v_ratio, 2),
            'RSI (14)': round(rsi_val, 2),
            'Turnover (M)': round(turnover / 1_000_000_000, 2)
        })
        
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        df_results = df_results.sort_values(by='Vol Ratio', ascending=False)
    return df_results, shortlist_keys

# --- 4. MAIN APP ---
def load_emiten():
    for f in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(f):
            try:
                df = pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)
                df.columns = [c.strip() for c in df.columns]
                return df
            except: continue
    return None

df_emiten = load_emiten()

if df_emiten is not None:
    st.sidebar.header("Filter Parameter")
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=900)
    
    if st.sidebar.button("🚀 Jalankan Analisa"):
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]
        
        with st.spinner('Menyaring harga (Filter Awal)...'):
            # Langkah 1: Ambil harga terakhir saja untuk SEMUA saham
            current_prices = get_current_prices(all_tickers)
            
            # Langkah 2: Saring mana yang masuk rentang 100 - 900
            saham_lolos_filter = current_prices[(current_prices >= min_p) & (current_prices <= max_p)].index.tolist()
            
        if saham_lolos_filter:
            st.info(f"Ditemukan {len(saham_lolos_filter)} saham dalam rentang harga. Menganalisa histori...")
            
            with st.spinner('Menarik data histori & indikator...'):
                # Langkah 3: Hanya tarik histori lengkap untuk saham yang lolos filter harga
                c_raw, v_raw = fetch_hist_data(saham_lolos_filter, date.today() - timedelta(days=30))
                
                if not c_raw.empty:
                    df_res, shortlists = get_signals(c_raw, v_raw)
                    
                    st.subheader("🎯 Top Pick Terpilih")
                    df_top = df_res[df_res['Status'] == "💎 TOP PICK"]
                    if not df_top.empty:
                        st.dataframe(df_top, use_container_width=True)
                    else:
                        st.info("Tidak ada yang lolos kriteria 'TOP PICK'.")
                        
                    st.divider()
                    st.subheader("📊 Hasil Screening Lengkap")
                    st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Tidak ada saham yang ditemukan dalam rentang harga tersebut.")
else:
    st.error("File database tidak ditemukan.")
