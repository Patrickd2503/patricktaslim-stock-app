import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")
st.title("🎯 Dashboard Akumulasi: Smart Money Monitor")

# --- 1. FITUR CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Menambahkan IHSG (^JKSE) sebagai benchmark perbandingan market
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume'], df['High'], df['Low']
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATABASE EMITEN ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'data.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)
                if 'Kode Saham' in df.columns:
                    return df, file_name
            except: continue
    
    # Data cadangan jika file tidak ditemukan
    default_data = pd.DataFrame({
        'Kode Saham': ['WINS', 'CNKO', 'KOIN', 'STRK', 'KAEF', 'ICON', 'SPRE', 'LIVE', 'VIVA', 'BUMI', 'GOTO']
    })
    return default_data, "Default Mode (File Not Found)"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI STYLING TABEL ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white' # Jenuh Beli
        if num <= 40: return 'background-color: #008000; color: white' # Area Akumulasi
    except: pass
    return ''

def highlight_outperform(row):
    # Memberi warna baris jika Market RS adalah Outperform
    return ['background-color: #1e3d59; color: white' if row['Market RS'] == 'Outperform' else '' for _ in row]

# --- 4. LOGIKA ANALISA TEKNIKAL ---
def get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    
    # Ambil Performa IHSG (20 hari terakhir)
    if "^JKSE" in df_c.columns:
        ihsg_c = df_c["^JKSE"].dropna()
        ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0
    else:
        ihsg_perf = 0

    for col in df_c.columns:
        if col == "^JKSE" or col == "": continue
        
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        # Kalkulasi MFI (Money Flow Index)
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf)))
        last_mfi = mfi_series.iloc[-1] if not np.isnan(mfi_series.iloc[-1]) else 50

        # Kalkulasi Tren MA20 & Vol SMA20
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        last_p = c.iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        
        trend = "Diatas MA20" if last_p > ma20 else "Dibawah MA20"
        
        # Status PVA
        pva = "Neutral"
        if p_change > 1 and v.iloc[-1] > v_sma20: pva = "Bullish Vol"
        elif p_change < -1 and v.iloc[-1] > v_sma20: pva = "Bearish Vol"
        elif abs(p_change) < 1 and v.iloc[-1] > v_sma20: pva = "Churning"

        # Market Relative Strength (RS)
        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        # Kriteria Shortlist: Bullish + MFI Rendah + Diatas MA20
        if is_analisa_lengkap:
            if pva == "Bullish Vol" and last_mfi < 55 and last_p > ma20:
                shortlist_keys.append(str(col).replace('.JK',''))

        results.append({
            'Kode Saham': str(col).replace('.JK',''),
            'Tren (MA20)': trend,
            'MFI (14D)': last_mfi,
            'PVA': pva,
            'Market RS': rs,
            'Last Price': int(last_p),
            'Vol/SMA20': v.iloc[-1] / v_sma20 if v_sma20 > 0 else 0
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. RENDER DASHBOARD ---
st.sidebar.info(f"Database: {loaded_file}")

if not df_emiten.empty:
    st.sidebar.header("⚙️ Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Pilih Kode Spesifik:", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=50)
    max_p = st.sidebar.number_input("Harga Max", value=20000)
    
    start_d = st.sidebar.date_input("Mulai", date(2026, 1, 5))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 10))

    if st.sidebar.button("🚀 Jalankan Analisa"):
        with st.spinner('Memproses data market...'):
            target_list = selected_tickers if selected_tickers else all_tickers
            tickers_jk = [str(k).strip() + ".JK" for k in target_list]
            
            df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c.empty:
                # Bersihkan MultiIndex jika ada
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                    df_h.columns = df_h.columns.get_level_values(1)
                    df_l.columns = df_l.columns.get_level_values(1)

                df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=True)
                df_analysis = df_analysis[(df_analysis['Last Price'] >= min_p) & (df_analysis['Last Price'] <= max_p)]

                # --- BAGIAN 1: GOLDEN SETUP ---
                st.subheader("💎 Golden Setup (Rekomendasi Entry Jam 10:30)")
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)].sort_values(by='MFI (14D)')
                
                if not df_top.empty:
                    # Menampilkan Tabel dengan Highlight & Formatting
                    st.dataframe(
                        df_top.style.apply(highlight_outperform, axis=1)
                                    .applymap(style_mfi, subset=['MFI (14D)'])
                                    .format({"MFI (14D)": "{:.1f}", "Vol/SMA20": "{:.2f}"}), 
                        use_container_width=True
                    )
                    st.info("💡 Baris berwarna biru gelap adalah saham yang **Outperform** (lebih kuat dari IHSG).")
                else:
                    st.warning("Belum ada saham yang memenuhi syarat ketat hari ini.")

                st.divider()
                
                # --- BAGIAN 2: SEMUA DATA ---
                st.write("### 📊 Monitor Seluruh Emiten")
                st.dataframe(
                    df_analysis.style.applymap(style_mfi, subset=['MFI (14D)'])
                                     .format({"MFI (14D)": "{:.1f}", "Vol/SMA20": "{:.2f}"}), 
                    use_container_width=True
                )
            else:
                st.error("Data tidak ditemukan. Cek koneksi atau ticker saham.")
else:
    st.error("Gagal memuat emiten.")
