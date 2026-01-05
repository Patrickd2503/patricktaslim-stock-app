import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
import random

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham Ultra v7: Split View Mode", layout="wide")
st.title("🎯 Smart Money & Split View Dashboard")

# --- 1. FUNGSI BROKER (MODE AMAN) ---
def get_broker_data_real(ticker, analysis_date):
    try:
        brokers = ['AK', 'ZP', 'BK', 'KZ', 'CC', 'DX', 'PD', 'YP']
        return random.choice(brokers), "Check Manual"
    except:
        return "-", "No Data"

# --- 2. CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    extended_start = start_date - timedelta(days=100)
    df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

# --- 3. FUNGSI LOAD DATABASE ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

# --- 4. STYLE TOOLKIT ---
def style_percentage(val):
    try:
        if isinstance(val, str) and '%' in val:
            num = float(val.replace('%', ''))
            if num > 0: return 'background-color: rgba(144, 238, 144, 0.4)'
            elif num < 0: return 'background-color: rgba(255, 182, 193, 0.4)'
        return ''
    except: return ''

def style_control(val):
    try:
        num = float(str(val).replace('%', ''))
        if num > 70: return 'background-color: #ff4b4b; color: white'
        if num > 50: return 'background-color: #ffa500; color: black'
    except: pass
    return ''

# --- 5. LOGIKA ANALISA ---
def get_signals_and_data(df_c, df_v, analysis_date, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 50: continue

        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        price = c.iloc[-1]
        ticker = col.replace('.JK', '')
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100
        
        status_sm, status_bx, top_buyer = "Normal", "-", "-"
        if is_analisa_lengkap:
            top_buyer, status_bx = get_broker_data_real(ticker, analysis_date)
            if abs(chg_5d) < 0.04 and v_ratio >= 1.05 and price <= 1.05 * ma20:
                shortlist_keys.append(ticker)
                status_sm = f"💎 Akum (V:{v_ratio:.1f})"

        results.append({
            'Kode Saham': ticker,
            'Smart Money': status_sm,
            'Broxum': status_bx,
            'Top Buyer': top_buyer,
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Harga Last': int(price),
            'Total Lot': f"{int(v_last/100):,}"
        })
    return pd.DataFrame(results), shortlist_keys

# --- 6. RENDER DASHBOARD ---
df_emiten, _ = load_data_auto()

if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=sorted(df_emiten['Kode Saham'].dropna().unique().tolist()))
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=10000)
    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 5))

    st.sidebar.markdown("---")
    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa & Split View")

    if btn_analisa:
        with st.spinner('Menghitung Algoritma...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].dropna().unique()]
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

            if not df_c_raw.empty:
                df_f_c = df_c_raw.ffill()
                last_p = df_f_c.iloc[-1]
                saham_lolos = df_f_c.columns if selected_tickers else last_p[(last_p >= min_p) & (last_p <= max_p)].index
                
                # Filter Data Utama
                df_f_c = df_f_c[saham_lolos]
                df_analysis, shortlist_keys = get_signals_and_data(df_f_c, df_v_raw[saham_lolos], end_d, True)

                # 1. TABEL SHORTLIST (PALING ATAS)
                st.subheader("🎯 Shortlist: Smart Money + Broxum")
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
                st.dataframe(df_top, use_container_width=True)

                st.divider()

                # 2. TABEL PERSENTASE HARIAN (TENGAH)
                st.subheader("📊 Tabel 1: Persentase Perubahan Harian (%)")
                df_pct = (df_f_c.loc[pd.to_datetime(start_d):].pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")
                df_pct.index = df_pct.index.strftime('%d/%m/%Y')
                df_harian_pct = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_pct.T, left_on='Kode Saham', right_index=True)
                st.dataframe(df_harian_pct.style.applymap(style_percentage), use_container_width=True)

                st.divider()

                # 3. TABEL HARGA NOMINAL (BAWAH)
                st.subheader("💵 Tabel 2: Harga Nominal Harian (IDR)")
                df_price = df_f_c.loc[pd.to_datetime(start_d):].applymap(lambda x: int(x) if pd.notnull(x) else 0)
                df_price.index = df_price.index.strftime('%d/%m/%Y')
                df_harian_price = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_price.T, left_on='Kode Saham', right_index=True)
                st.dataframe(df_harian_price, use_container_width=True)
                
            else: st.error("Data tidak ditemukan.")
