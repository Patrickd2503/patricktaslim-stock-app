import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
import random

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham Ultra v10", layout="wide")
st.title("🎯 Smart Money & Split View Dashboard")

# --- 1. FUNGSI BROKER (MOCKUP/PLACEHOLDER) ---
def get_broker_data_real(ticker, analysis_date):
    brokers = ['AK', 'ZP', 'BK', 'KZ', 'CC', 'DX', 'PD', 'YP']
    return random.choice(brokers), "Check Manual"

# --- 2. CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Buffer data 60 hari ke belakang agar indikator awal tidak kosong
    extended_start = start_date - timedelta(days=60)
    try:
        df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume']
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. FUNGSI LOAD DATABASE ---
def load_data_auto():
    # Mencari file database di direktori yang sama
    for f in ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']:
        if os.path.exists(f):
            try:
                return (pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)), f
            except: continue
    return None, None

# --- 4. STYLE TOOLKIT ---
def style_percentage(val):
    try:
        if isinstance(val, str) and '%' in val:
            num = float(val.replace('%', ''))
            if num > 0: return 'background-color: rgba(144, 238, 144, 0.4)'
            elif num < 0: return 'background-color: rgba(255, 182, 193, 0.4)'
    except: pass
    return ''

# --- 5. LOGIKA ANALISA ---
def get_signals_and_data(df_c, df_v, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        # Mengambil data individu per saham
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 5: continue
        
        price = c.iloc[-1]
        v_last = v.iloc[-1]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        ticker = str(col).replace('.JK', '')
        
        status_sm, status_bx, top_buyer = "Normal", "-", "-"
        if is_analisa_lengkap:
            top_buyer, status_bx = get_broker_data_real(ticker, None)
            chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5] if len(c) >= 5 else 0
            # Kriteria Akumulasi Sederhana
            if abs(chg_5d) < 0.05 and v_ratio > 1.1:
                status_sm = "💎 Akumulasi"
                shortlist_keys.append(ticker)

        results.append({
            'Kode Saham': ticker, 'Smart Money': status_sm, 'Broxum': status_bx,
            'Top Buyer': top_buyer, 'Vol Ratio': round(v_ratio, 2),
            'Harga Last': int(price), 'Total Lot': f"{int(v_last/100):,}"
        })
    return pd.DataFrame(results), shortlist_keys

# --- 6. RENDER DASHBOARD ---
df_emiten, _ = load_data_auto()

if df_emiten is not None:
    # --- SIDEBAR ---
    st.sidebar.header("Filter & Parameter")
    all_codes = sorted(df_emiten['Kode Saham'].dropna().unique())
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=all_codes)
    
    h_min = st.sidebar.number_input("Harga Min", value=50)
    h_max = st.sidebar.number_input("Harga Max", value=10000)
    
    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2025, 12, 17))

    st.sidebar.markdown("---")
    # Opsi Tarik Data Sesuai Permintaan User
    btn_split = st.sidebar.button("📊 1. Split View")
    btn_full = st.sidebar.button("🚀 2. Analisa Lengkap")

    if btn_split or btn_full:
        with st.spinner('Menghubungkan ke Bursa...'):
            # Menentukan daftar emiten yang akan ditarik
            if selected_tickers:
                df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)]
            else:
                df_to_f = df_emiten

            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            df_c, df_v = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

            if not df_c.empty:
                # FIX: Menangani Multi-Index Yahoo Finance (penyebab tabel "empty")
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                
                # Forward fill untuk menangani hari libur/data bolong
                df_c = df_c.ffill()
                df_v = df_v.fillna(0)
                
                # LOGIKA PRIORITAS: Jika input kode manual, abaikan filter harga
                if selected_tickers:
                    df_f_c = df_c
                    df_f_v = df_v
                else:
                    # Cari baris terakhir yang ada datanya untuk filter harga
                    last_prices = df_c.iloc[-1]
                    valid_cols = last_prices[(last_prices >= h_min) & (last_prices <= h_max)].index
                    df_f_c = df_c[valid_cols]
                    df_f_v = df_v[valid_cols]
                
                # Jalankan Analisa
                df_analysis, shortlist_keys = get_signals_and_data(df_f_c, df_f_v, is_analisa_lengkap=btn_full)

                # --- OUTPUT TAMPILAN ---
                
                # A. TABEL SHORTLIST (Hanya muncul jika tombol Analisa Lengkap diklik)
                if btn_full:
                    st.subheader("🎯 Shortlist: Smart Money + Broxum")
                    df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
                    if not df_top.empty:
                        st.dataframe(df_top, use_container_width=True)
                    else:
                        st.info("Tidak ada saham masuk kriteria akumulasi.")
                    st.divider()

                # B. TABEL PERSENTASE (Muncul di kedua tombol - Split View)
                st.subheader("📈 Tabel 1: Persentase Perubahan Harian (%)")
                # Filter data sesuai rentang tanggal yang dipilih user
                df_daily_pct = df_f_c.loc[pd.to_datetime(start_d):pd.to_datetime(end_d)]
                df_pct_res = (df_daily_pct.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")
                df_pct_res.index = df_pct_res.index.strftime('%d/%m/%Y')
                
                df_out_pct = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_pct_res.T, left_on='Kode Saham', right_index=True)
                st.dataframe(df_out_pct.style.applymap(style_percentage), use_container_width=True)

                # C. TABEL HARGA (Muncul di kedua tombol - Split View)
                st.subheader("💵 Tabel 2: Harga Nominal Harian (IDR)")
                df_daily_price = df_f_c.loc[pd.to_datetime(start_d):pd.to_datetime(end_d)]
                df_price_res = df_daily_price.applymap(lambda x: int(x) if pd.notnull(x) else 0)
                df_price_res.index = df_price_res.index.strftime('%d/%m/%Y')
                
                df_out_price = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_price_res.T, left_on='Kode Saham', right_index=True)
                st.dataframe(df_out_price, use_container_width=True)
            else:
                st.error("Data tidak ditemukan. Periksa koneksi atau rentang tanggal.")
else:
    st.error("File database emiten (Excel/CSV) tidak ditemukan di folder.")
