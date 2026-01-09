import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")

st.title("🎯 Smart Money Monitor: Dashboard Akumulasi BEI")

# --- 1. LOAD DATA DARI GITHUB (FREE FLOAT) ---
@st.cache_data(ttl=3600)
def load_free_float_github():
    url = "https://github.com/Patrickd2503/patricktaslim-stock-app/raw/main/FreeFloat.xlsx"
    try:
        df_ff = pd.read_excel(url)
        df_ff.columns = df_ff.columns.str.strip()
        if len(df_ff.columns) >= 2:
            df_ff = df_ff.rename(columns={df_ff.columns[0]: 'Ticker', df_ff.columns[1]: 'FF_Percent'})
        df_ff['Ticker'] = df_ff['Ticker'].astype(str).str.strip().str.upper()
        return df_ff
    except:
        return pd.DataFrame()

# --- 2. FETCH DATA MARKET (DIPERBAIKI) ---
@st.cache_data(ttl=1800)
def fetch_yf_data(tickers):
    # Mengambil data 60 hari ke belakang agar indikator MA selalu terisi
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=60)
    try:
        # Menggunakan group_by='column' untuk stabilitas MultiIndex
        df = yf.download(list(tickers), start=start_dt, end=end_dt, threads=True, progress=False, group_by='column')
        
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        # Penanganan struktur data yfinance yang sering berubah
        if len(tickers) == 1:
            return df[['Close']].rename(columns={'Close': tickers[0]}), df[['Volume']].rename(columns={'Volume': tickers[0]})
        
        return df['Close'], df['Volume']
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. LOAD DATABASE LOKAL ---
def load_local_codes():
    for file in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(file):
            try:
                df = pd.read_csv(file) if file.endswith('.csv') else pd.read_excel(file)
                return df
            except: continue
    return None

# --- 4. LOGIKA ANALISA ---
def run_analysis(df_c, df_v, df_ff_ref):
    results = []
    for ticker_jk in df_c.columns:
        ticker_clean = str(ticker_jk).replace('.JK', '').upper()
        prices = df_c[ticker_jk].dropna()
        volumes = df_v[ticker_jk].dropna()
        
        if len(prices) < 10: continue
        
        last_p = prices.iloc[-1]
        v_sma5 = volumes.rolling(5).mean().iloc[-1]
        v_sma20 = volumes.rolling(20).mean().iloc[-1]
        v_last = volumes.iloc[-1]
        
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        v_ma_ratio = v_sma5 / v_sma20 if v_sma20 > 0 else 0
        vol_control = (v_ratio / (v_ratio + 1)) * 100
        chg_5d = (prices.iloc[-1] - prices.iloc[-5]) / prices.iloc[-5] if len(prices) >= 5 else 0
        
        ff_val = "N/A"
        if not df_ff_ref.empty:
            match = df_ff_ref[df_ff_ref['Ticker'] == ticker_clean]
            if not match.empty: ff_val = match['FF_Percent'].values[0]

        status = "Normal"
        if abs(chg_5d) < 0.03 and v_ratio >= 1.1:
            status = f"💎 Akumulasi (V:{v_ratio:.1f})"
        elif chg_5d > 0.05: status = "🚀 Markup"

        results.append({
            'Ticker': ticker_clean,
            'Sinyal': status,
            'Harga': int(last_p),
            'Chg 5D': f"{chg_5d*100:.1f}%",
            'Vol Control': f"{vol_control:.1f}%",
            'Vol Ratio': round(v_ma_ratio, 2),
            'Free Float': f"{ff_val:.1f}%" if isinstance(ff_val, (int, float)) else ff_val,
            'Vol Lot': f"{int(v_last/100):,}"
        })
    return pd.DataFrame(results)

# --- 5. UI ---
df_master = load_local_codes()
df_ff = load_free_float_github()

if df_master is not None:
    list_saham = sorted(df_master.iloc[:, 0].dropna().unique().tolist())
    selected = st.sidebar.multiselect("Pilih Saham (Kosongkan = Semua):", options=list_saham)
    
    st.sidebar.write("**Rentang Harga (IDR):**")
    col_min, col_max = st.sidebar.columns(2)
    min_p = col_min.number_input("Min", value=50, step=10)
    max_p = col_max.number_input("Max", value=500, step=10)
    
    if st.sidebar.button("🔍 Jalankan Analisa"):
        # Jika tidak ada yang dipilih, ambil 50 saham pertama saja untuk menghindari limit YFinance
        # Atau Anda bisa tetap memproses semua jika koneksi stabil
        list_to_process = selected if selected else list_saham
        
        tickers_jk = [str(s).strip() + ".JK" for s in list_to_process]
        
        with st.spinner('Menghubungi Yahoo Finance...'):
            df_c, df_v = fetch_yf_data(tickers_jk)
            
            if not df_c.empty:
                # FILTER HARGA DI SINI
                last_prices = df_c.ffill().iloc[-1]
                saham_lolos = last_prices[(last_prices >= min_p) & (last_prices <= max_p)].index
                
                if not saham_lolos.empty:
                    df_final = run_analysis(df_c[saham_lolos], df_v[saham_lolos], df_ff)
                    st.dataframe(df_final.sort_values('Sinyal', ascending=False), use_container_width=True)
                else:
                    st.warning(f"Tidak ada saham dalam rentang harga {min_p} - {max_p}")
            else:
                st.error("Data tidak ditemukan. Kemungkinan Yahoo Finance menolak permintaan (Too many requests) atau market data belum update.")
else:
    st.error("File 'Kode Saham.xlsx' tidak terdeteksi.")
