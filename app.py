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

# --- 1. FITUR CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low']
        else:
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']]
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATABASE EMITEN (MENGGUNAKAN FreeFloat.xlsx) ---
def load_data_auto():
    # Pastikan file ini berada di folder yang sama dengan script python Anda
    file_name = 'FreeFloat.xlsx'
    if os.path.exists(file_name):
        try: 
            df = pd.read_excel(file_name)
            # Standarisasi kolom
            if 'Kode Saham' in df.columns:
                # Bersihkan spasi jika ada
                df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip()
                if 'Free Float' not in df.columns:
                    df['Free Float'] = 0
                return df, file_name
        except Exception as e:
            st.error(f"Gagal membaca file {file_name}: {e}")
    
    # Data cadangan jika file TIDAK ditemukan (Default Mode)
    default_data = pd.DataFrame({
        'Kode Saham': ['WINS', 'CNKO', 'KOIN', 'STRK', 'KAEF', 'ICON', 'BUMI', 'GOTO', 'BBCA', 'BMRI', 'TLKM', 'ASII', 'ADRO', 'PTBA', 'UNVR'],
        'Free Float': [30, 45, 20, 15, 10, 50, 60, 70, 40, 40, 40, 40, 35, 30, 15]
    })
    return default_data, "Default Mode (File FreeFloat.xlsx TIDAK ditemukan)"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI STYLING ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white'
        if num <= 40: return 'background-color: #008000; color: white'
    except: pass
    return ''

def style_market_rs(val):
    if val == 'Outperform':
        return 'color: #006400; font-weight: bold;' # Hijau Gelap
    return 'color: #ff4b4b;'

def style_pva(val):
    if val == 'Bullish Vol': return 'background-color: rgba(0, 255, 0, 0.2);'
    if val == 'Bearish Vol': return 'background-color: rgba(255, 0, 0, 0.2);'
    return ''

def style_percentage(val):
    try:
        if val > 0: return 'color: green'
        elif val < 0: return 'color: red'
    except: pass
    return ''

# --- 4. LOGIKA ANALISA TEKNIKAL ---
def get_signals_and_data(df_c, df_v, df_h, df_l, df_ref, is_analisa_lengkap=False, min_avg_vol_lot=100000):
    results, shortlist_keys = [], []
    
    # Konversi input Lot ke Lembar untuk perhitungan yfinance
    min_avg_vol_lembar = min_avg_vol_lot * 100
    
    if "^JKSE" in df_c.columns:
        ihsg_c = df_c["^JKSE"].dropna()
        ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0
    else:
        ihsg_perf = 0

    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col): continue
        
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        if avg_vol20 < min_avg_vol_lembar: continue

        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        
        # Penanganan pembagian nol pada MFI
        if neg_mf.iloc[-1] == 0:
            last_mfi = 100
        else:
            mfi_val = 100 - (100 / (1 + (pos_mf / neg_mf)))
            last_mfi = mfi_val.iloc[-1] if not np.isnan(mfi_val.iloc[-1]) else 50
        
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        last_p = c.iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        
        pva = "Neutral"
        if p_change > 0.5 and v.iloc[-1] > v_sma20: pva = "Bullish Vol"
        elif p_change < -0.5 and v.iloc[-1] > v_sma20: pva = "Bearish Vol"

        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        ticker_name = str(col).replace('.JK','')
        ff_val = df_ref[df_ref['Kode Saham'] == ticker_name]['Free Float'].values[0] if ticker_name in df_ref['Kode Saham'].values else 0

        # SYARAT SHORTLIST
        if is_analisa_lengkap and pva == "Bullish Vol" and last_p > ma20 and last_mfi < 65:
            shortlist_keys.append(ticker_name)

        results.append({
            'Kode Saham': ticker_name,
            'Free Float (%)': ff_val,
            'MFI (14D)': last_mfi,
            'PVA': pva,
            'Market RS': rs,
            'Tren': "UP" if last_p > ma20 else "DOWN",
            'Last Price': int(last_p),
            'Vol/SMA20': v.iloc[-1] / v_sma20 if v_sma20 > 0 else 0,
            'AvgVol20 (Lot)': int(avg_vol20 / 100)
        })
        
    return pd.DataFrame(results), shortlist_keys

# --- 5. UI SIDEBAR ---
st.sidebar.header("⚙️ Konfigurasi")
target_list = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (Kosongkan = Semua):", options=target_list)

min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)

# INPUT SEKARANG DALAM SATUAN LOT
# Default: 100.000 Lot (Setara 10jt lembar)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=100000)

max_ff = st.sidebar.slider("Maximal Free Float (%)", 0, 100, 100)

today = date.today()
start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
end_d = st.sidebar.date_input("Tanggal Akhir", today)

st.sidebar.markdown("---")
show_histori = st.sidebar.checkbox("📊 Tampilkan Analisa Histori")
btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

# --- 6. OUTPUT DASHBOARD ---
if btn_analisa:
    with st.spinner('Scanning market data...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [str(k).strip() + ".JK" for k in active_list]
        
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, df_emiten, True, min_vol_lot)
            
            # Filter Harga & Maximal Free Float
            df_analysis = df_analysis[
                (df_analysis['Last Price'] >= min_p) & 
                (df_analysis['Last Price'] <= max_p) &
                (df_analysis['Free Float (%)'] <= max_ff)
            ]

            m1, m2, m3 = st.columns(3)
            m1.metric("Total Scan", len(df_analysis))
            m2.metric("Shortlist Potensial", len(shortlist_keys))
            m3.metric("Source File", loaded_file)

            # TABEL 1: SHORTLIST
            st.subheader("🔥 Smart Money Shortlist (Top Picks)")
            df_short = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
            if not df_short.empty:
                st.dataframe(df_short.style.applymap(style_mfi, subset=['MFI (14D)'])
                             .applymap(style_market_rs, subset=['Market RS'])
                             .applymap(style_pva, subset=['PVA'])
                             .format({'Vol/SMA20': "{:.2f}", 'MFI (14D)': "{:.2f}", 'Free Float (%)': "{:.1f}%"}), 
                             use_container_width=True)
            else:
                st.info("Tidak ada saham yang memenuhi kriteria shortlist.")

            st.markdown("---")

            # TABEL 2: FULL ANALISA
            st.subheader("🔍 Seluruh Hasil Analisa")
            st.dataframe(df_analysis.style.applymap(style_mfi, subset=['MFI (14D)'])
                         .applymap(style_market_rs, subset=['Market RS'])
                         .format({'Vol/SMA20': "{:.2f}", 'MFI (14D)': "{:.2f}", 'Free Float (%)': "{:.1f}%"}), 
                         use_container_width=True, height=400)

            if show_histori:
                st.markdown("---")
                st.subheader("📈 Analisa Histori")
                tab_h1, tab_h2 = st.tabs(["Perubahan Harga (%)", "Volume Transaksi"])
                with tab_h1:
                    # Filter hanya saham yang ada di hasil analisa utama
                    hist_df = (df_c[ [c for c in df_c.columns if c.replace('.JK','') in df_analysis['Kode Saham'].values] ].pct_change() * 100).tail(10)
                    st.dataframe(hist_df.style.applymap(style_percentage).format("{:.2f}%"), use_container_width=True)
                with tab_h2:
                    vol_df = df_v[ [c for c in df_v.columns if c.replace('.JK','') in df_analysis['Kode Saham'].values] ].tail(10)
                    st.dataframe(vol_df, use_container_width=True)

        else:
            st.error("Data tidak ditemukan. Pastikan koneksi internet aktif.")
else:
    if "TIDAK ditemukan" in loaded_file:
        st.warning(f"⚠️ {loaded_file}. Harap letakkan file FreeFloat.xlsx di folder yang sama dengan script.")
    else:
        st.success(f"✅ Berhasil memuat data dari {loaded_file}")
    st.info("Atur filter di sidebar dan klik 'Jalankan Analisa'.")
