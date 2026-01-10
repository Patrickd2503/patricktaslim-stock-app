import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")
st.title("🎯 Dashboard Akumulasi: Smart Money Monitor")

# --- 1. FITUR CACHE ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        # Menangani struktur data yfinance yang bisa berubah (MultiIndex)
        close = df['Close']
        volume = df['Volume']
        high = df['High']
        low = df['Low']
        return close, volume, high, low
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATA ---
def load_data_auto():
    # Menambahkan list file yang mungkin ada
    POSSIBLE_FILES = ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.xlsx - Sheet1.csv', 'data.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)
                # Pastikan kolom 'Kode Saham' ada
                if 'Kode Saham' in df.columns:
                    return df, file_name
            except: continue
    
    # JIKA FILE TIDAK DITEMUKAN, PAKAI DATA DEFAULT (Contoh Top 10 BEI)
    default_data = pd.DataFrame({
        'Kode Saham': ['BBCA', 'BBRI', 'TLKM', 'BMRI', 'ASII', 'GOTO', 'BUMI', 'GIAA', 'BIPI', 'ANTM'],
        'Nama Perusahaan': ['Bank BCA', 'Bank BRI', 'Telkom', 'Bank Mandiri', 'Astra', 'Goto', 'Bumi Resources', 'Garuda', 'Astrindo', 'Antam']
    })
    return default_data, "Default (File Not Found)"

# Inisialisasi df_emiten di awal agar NameError hilang
df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI PEWARNAAN ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white' 
        if num <= 35: return 'background-color: #008000; color: white' 
    except: pass
    return ''

def style_trend(val):
    if val == "Diatas MA20": return 'color: #008000; font-weight: bold'
    if val == "Dibawah MA20": return 'color: #ff4b4b'
    return ''

# --- 4. LOGIKA ANALISA ---
def get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    
    # Cek IHSG
    if "^JKSE" in df_c.columns:
        ihsg_c = df_c["^JKSE"].dropna()
        ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0
    else:
        ihsg_perf = 0

    for col in df_c.columns:
        if col == "^JKSE" or col == "": continue
        
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 25: continue
        
        # MFI
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf)))
        last_mfi = mfi_series.iloc[-1] if not np.isnan(mfi_series.iloc[-1]) else 50

        # Trend & PVA
        ma20 = c.rolling(20).mean().iloc[-1]
        last_p = c.iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        
        trend = "Diatas MA20" if last_p > ma20 else "Dibawah MA20"
        
        pva = "Neutral"
        if p_change > 1 and v.iloc[-1] > v_sma20: pva = "Bullish Vol"
        elif p_change < -1 and v.iloc[-1] > v_sma20: pva = "Bearish Vol"
        elif abs(p_change) < 1 and v.iloc[-1] > v_sma20: pva = "Churning"

        # RS
        s_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if s_perf > ihsg_perf else "Underperform"

        # Shortlist Logic: Entry Jam 10:30 (Swing 2 Minggu)
        if is_analisa_lengkap:
            if pva == "Bullish Vol" and last_mfi < 55 and trend == "Diatas MA20":
                shortlist_keys.append(str(col).replace('.JK',''))

        results.append({
            'Kode Saham': str(col).replace('.JK',''),
            'Tren (MA20)': trend,
            'MFI (14D)': round(last_mfi, 1),
            'PVA': pva,
            'Market RS': rs,
            'Last Price': int(last_p),
            'Vol/SMA20': round(v.iloc[-1] / v_sma20, 2) if v_sma20 > 0 else 0
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. RENDER DASHBOARD ---
st.sidebar.info(f"File Terdeteksi: {loaded_file}")

if not df_emiten.empty:
    st.sidebar.header("Filter & Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode (Kosongkan untuk semua):", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=50)
    max_p = st.sidebar.number_input("Harga Max", value=20000)
    
    # Default ke Jan 2026 sesuai skenario user
    start_d = st.sidebar.date_input("Mulai", date(2026, 1, 5))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 10))

    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa Jam 10:30")

    if btn_analisa:
        with st.spinner('Menganalisa data market...'):
            target_list = selected_tickers if selected_tickers else all_tickers
            tickers_jk = [str(k).strip() + ".JK" for k in target_list]
            
            df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c.empty:
                # Membersihkan kolom jika MultiIndex
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                    df_h.columns = df_h.columns.get_level_values(1)
                    df_l.columns = df_l.columns.get_level_values(1)

                df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=True)
                
                # Filter Harga
                df_analysis = df_analysis[(df_analysis['Last Price'] >= min_p) & (df_analysis['Last Price'] <= max_p)]

                # TABEL 1: SHORTLIST
                st.subheader("💎 Golden Setup untuk Senin (Entry Jam 10:30)")
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)].sort_values(by='MFI (14D)')
                
                if not df_top.empty:
                    st.success(f"Ditemukan {len(df_top)} saham untuk Swing 2 Minggu.")
                    st.dataframe(df_top.style.applymap(style_mfi, subset=['MFI (14D)'])
                                         .applymap(style_trend, subset=['Tren (MA20)']), use_container_width=True)
                else:
                    st.warning("Tidak ada saham memenuhi syarat ketat (MA20 + MFI < 55). Cek tabel monitor di bawah.")

                st.divider()
                st.write("### 📊 Monitor Arus Uang (MFI & PVA)")
                st.dataframe(df_analysis.style.applymap(style_mfi, subset=['MFI (14D)'])
                                         .applymap(style_trend, subset=['Tren (MA20)']), use_container_width=True)
            else:
                st.error("Data gagal diambil dari Yahoo Finance. Cek koneksi atau simbol saham.")
else:
    st.error("Gagal memuat data emiten. Pastikan file 'Kode Saham.xlsx' sudah di-upload.")
