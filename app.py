import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO
import requests

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")
st.title("🎯 Dashboard Akumulasi: Smart Money Monitor")

# --- 1. LOAD DATA EXTERNAL (GITHUB) ---
@st.cache_data(ttl=86400) # Cache 24 jam
def load_free_float_github():
    # Menggunakan link raw agar bisa dibaca pandas
    url = "https://github.com/Patrickd2503/patricktaslim-stock-app/raw/main/FreeFloat.xlsx"
    try:
        df_ff = pd.read_excel(url)
        # Pastikan kolom seragam (biasanya: 'Ticker' dan 'Free Float')
        # Sesuaikan nama kolom jika di file Anda berbeda
        return df_ff
    except Exception as e:
        st.error(f"Gagal memuat data Free Float dari GitHub: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    extended_start = start_date - timedelta(days=365)
    try:
        df = yf.download(list(tickers), start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty: return pd.DataFrame(), pd.DataFrame()
        
        if len(tickers) == 1:
            return df[['Close']].rename(columns={'Close': tickers[0]}), df[['Volume']].rename(columns={'Volume': tickers[0]})
        
        return df['Close'], df['Volume']
    except Exception as e:
        st.error(f"YFinance Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATA LOKAL (KODE EMITEN) ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

df_emiten, _ = load_data_auto()
df_free_float_master = load_free_float_github()

# --- 3. LOGIKA ANALISA ---
def get_signals_and_data(df_c, df_v, df_ff_ref, is_analisa_lengkap=False):
    results = []
    shortlist_keys = []
    
    for col in df_c.columns:
        ticker_clean = str(col).replace('.JK','')
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 20: continue
        
        # Perhitungan Teknis
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        v_ma_ratio = v_sma5 / v_sma20 if v_sma20 > 0 else 0
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100 
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5] if len(c) >= 5 else 0
        
        # Ambil Free Float dari Dataframe GitHub
        ff_val = "N/A"
        if not df_ff_ref.empty:
            # Asumsi kolom di Excel GitHub bernama 'Ticker' dan 'Free Float'
            match = df_ff_ref[df_ff_ref['Ticker'] == ticker_clean]
            if not match.empty:
                ff_val = match['Free Float'].values[0]

        status = "Normal"
        if is_analisa_lengkap:
            is_sideways = abs(chg_5d) < 0.03
            is_high_control = vol_control_pct > 65
            # Syarat Tambahan: Liquiditas (Contoh: Nilai transaksi > 500jt)
            is_liquid = (v_last * c.iloc[-1]) > 500_000_000 
            
            # Logika Akumulasi
            if is_sideways and v_ratio >= 1.2:
                status = f"💎 Akumulasi (V:{v_ratio:.1f})"
                if is_high_control and is_liquid:
                    shortlist_keys.append(ticker_clean)
            elif chg_5d > 0.05: status = "🚀 Markup"

        results.append({
            'Kode Saham': ticker_clean,
            'Analisa Akumulasi': status,
            'Harga': int(c.iloc[-1]),
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Ratio Vol MA5/MA20': round(v_ma_ratio, 2),
            'Free Float (%)': f"{ff_val:.2f}%" if isinstance(ff_val, (int, float)) else ff_val,
            'Total Lot (Today)': f"{int(v_last/100):,}"
        })
        
    return pd.DataFrame(results), shortlist_keys

# --- 4. RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=50)
    max_p = st.sidebar.number_input("Harga Max", value=10000)
    start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=30))
    end_d = st.sidebar.date_input("Akhir", date.today())

    if st.sidebar.button("🚀 Jalankan Analisa"):
        with st.spinner('Menghubungkan ke GitHub & Yahoo Finance...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c_raw.empty:
                last_p = df_c_raw.ffill().iloc[-1]
                saham_lolos = last_p[(last_p >= min_p) & (last_p <= max_p)].index
                
                df_analysis, shortlist = get_signals_and_data(df_c_raw[saham_lolos], df_v_raw[saham_lolos], df_free_float_master, is_analisa_lengkap=True)
                
                if shortlist:
                    st.success(f"🔥 **Shortlist Akumulasi:** {', '.join(shortlist)}")
                
                st.dataframe(df_analysis, use_container_width=True)
            else:
                st.error("Data tidak ditemukan.")
else:
    st.warning("File 'Kode Saham.xlsx' lokal diperlukan untuk list emiten.")
