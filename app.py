import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os
from io import BytesIO

# --- 1. CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI v12 - Momentum", layout="wide")

# Custom CSS untuk tampilan lebih modern
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stDataFrame { border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🚀 Smart Momentum Monitor")
st.subheader("RSI, MACD, & Volume Explosion Strategy")

# --- 2. FUNGSI CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Buffer 1 tahun agar perhitungan RSI dan MACD akurat (perlu data histori)
    extended_start = start_date - timedelta(days=365)
    try:
        df = yf.download(list(tickers), start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        # Penanganan format data yfinance terbaru
        if isinstance(df.columns, pd.MultiIndex):
            close_df = df['Close']
            volume_df = df['Volume']
        else:
            close_df = df[['Close']]
            volume_df = df[['Volume']]
            
        return close_df, volume_df
    except Exception as e:
        st.error(f"Error saat mengambil data: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- 3. LOAD DATABASE EMITEN ---
def load_emiten():
    POSSIBLE_FILES = ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.xlsx - Sheet1.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)
                # Standarisasi nama kolom
                df.columns = [c.strip() for c in df.columns]
                return df
            except: continue
    return None

# --- 4. LOGIKA ANALISA MOMENTUM ---
def get_signals_and_data(df_c, df_v, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    
    if df_c.empty:
        return pd.DataFrame(), []

    for col in df_c.columns:
        # 1. Persiapan Data
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        
        if len(c) < 35: continue # Minimal data untuk indikator teknikal
        
        # 2. Hitung Indikator Teknikal
        # RSI 14
        rsi = ta.rsi(c, length=14)
        rsi_last = rsi.iloc[-1] if rsi is not None and not rsi.empty else 50
        
        # MACD (12, 26, 9)
        macd_df = ta.macd(c, fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            macd_hist = macd_df['MACDh_12_26_9'].iloc[-1]
            macd_val = macd_df['MACD_12_26_9'].iloc[-1]
            macd_sig = macd_df['MACDs_12_26_9'].iloc[-1]
        else:
            macd_hist, macd_val, macd_sig = 0, 0, 0
            
        # Volume Spike (Bandingkan dengan rata-rata 20 hari)
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma20 if v_sma20 > 0 else 0
        
        # Price Action 5 Hari
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5] if len(c) >= 5 else 0
        ticker = str(col).replace('.JK','')

        # 3. Kriteria Shortlist (Target Naik Cepat)
        is_rsi_strong = 45 < rsi_last < 72  # Tenaga kuat tapi belum jenuh beli
        is_macd_bullish = macd_hist > 0 and macd_val > macd_sig # Golden cross/bullish momentum
        is_vol_spike = v_ratio > 1.8       # Volume minimal 1.8x rata-rata sebulan
        is_breakout = 0.01 < chg_5d < 0.08 # Harga sudah mulai bergerak naik

        status = "Konsolidasi"
        if is_analisa_lengkap:
            # Syarat Tambahan: Likuiditas (min 500 lot transaksi)
            if (v_last / 100) > 500:
                if is_rsi_strong and is_macd_bullish and is_vol_spike:
                    status = "🔥 STRONG BUY"
                    shortlist_keys.append(ticker)
                elif is_macd_bullish:
                    status = "⤴️ Reversal"
                elif is_breakout:
                    status = "🚀 Momentum"

        results.append({
            'Kode Saham': ticker,
            'Analisa': status,
            'Last Price': int(c.iloc[-1]),
            'RSI (14)': round(rsi_last, 2),
            'MACD Hist': round(macd_hist, 2),
            'Vol Ratio': round(v_ratio, 2),
            'Chg 5D (%)': f"{chg_5d*100:.1f}%"
        })
        
    return pd.DataFrame(results), shortlist_keys

# --- 5. INTERFACE UTAMA ---
df_emiten = load_emiten()

if df_emiten is not None:
    # Sidebar
    st.sidebar.header("Filter Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].unique().tolist())
    selected = st.sidebar.multiselect("Pantau Kode Spesifik:", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=50)
    max_p = st.sidebar.number_input("Harga Max", value=5000)
    
    # Range tanggal (Gunakan 1 bulan terakhir untuk deteksi momentum)
    start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=30))
    end_d = st.sidebar.date_input("Akhir", date.today())

    if st.sidebar.button("🚀 Jalankan Analisa"):
        with st.spinner('Menganalisa Chart & Volume...'):
            # Filter Emiten
            to_process = df_emiten[df_emiten['Kode Saham'].isin(selected)] if selected else df_emiten
            tickers_jk = [str(t).strip() + ".JK" for t in to_process['Kode Saham']]
            
            c_raw, v_raw = fetch_yf_all_data(tickers_jk, start_d, end_d)
            
            if not c_raw.empty:
                # Filter harga saat ini
                last_p = c_raw.ffill().iloc[-1]
                saham_lolos = last_p[(last_p >= min_p) & (last_p <= max_p)].index
                
                df_res, shortlists = get_signals_and_data(c_raw[saham_lolos], v_raw[saham_lolos], True)
                
                if not df_res.empty:
                    # 1. Tampilan Shortlist
                    st.subheader("🎯 Shortlist Terpilih (Potensi Cepat)")
                    df_top = df_res[df_res['Kode Saham'].isin(shortlists)]
                    
                    if not df_top.empty:
                        st.success(f"Ditemukan {len(df_top)} Saham dengan konfirmasi Smart Money.")
                        st.dataframe(df_top.style.background_gradient(subset=['Vol Ratio'], cmap='Greens'), use_container_width=True)
                    else:
                        st.info("Belum ada saham yang memenuhi kriteria 'Strong Buy' hari ini.")
                    
                    # 2. Tabel Lengkap
                    st.divider()
                    st.subheader("📊 Seluruh Hasil Screening")
                    st.dataframe(df_res, use_container_width=True)
                else:
                    st.warning("Tidak ada saham yang memenuhi filter dasar.")
            else:
                st.error("Gagal mengambil data dari Yahoo Finance.")
else:
    st.error("File 'Kode Saham.xlsx' tidak ditemukan di direktori.")
