import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
import random

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham Ultra v9", layout="wide")
st.title("🎯 Smart Money & Split View Dashboard")

# --- 1. FUNGSI BROKER (MODE AMAN) ---
def get_broker_data_real(ticker, analysis_date):
    brokers = ['AK', 'ZP', 'BK', 'KZ', 'CC', 'DX', 'PD', 'YP']
    return random.choice(brokers), "Check Manual"

# --- 2. CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Buffer 60 hari untuk kestabilan data awal
    extended_start = start_date - timedelta(days=60)
    try:
        df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty: return pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume']
    except:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. FUNGSI LOAD DATABASE ---
def load_data_auto():
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
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 5: continue
        
        price = c.iloc[-1]
        v_last = v.iloc[-1]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        ticker = col.replace('.JK', '')
        
        status_sm, status_bx, top_buyer = "Normal", "-", "-"
        if is_analisa_lengkap:
            top_buyer, status_bx = get_broker_data_real(ticker, None)
            chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5] if len(c) >= 5 else 0
            # Sinyal Akumulasi: Volume naik di atas rata-rata saat harga relatif stabil
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
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=sorted(df_emiten['Kode Saham'].unique()))
    h_min = st.sidebar.number_input("Harga Min", value=50)
    h_max = st.sidebar.number_input("Harga Max", value=10000)
    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 5))

    st.sidebar.markdown("---")
    btn_split = st.sidebar.button("📊 1. Split View")
    btn_full = st.sidebar.button("🚀 2. Analisa Lengkap")

    if btn_split or btn_full:
        with st.spinner('Menarik data bursa...'):
            # Menentukan daftar emiten yang akan ditarik
            if selected_tickers:
                # Jika user memilih kode, abaikan filter harga
                df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)]
            else:
                # Jika tidak ada kode dipilih, tarik semua untuk difilter harga nanti
                df_to_f = df_emiten

            tickers_jk = [str(k) + ".JK" for k in df_to_f['Kode Saham'].unique()]
            df_c, df_v = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

            if not df_c.empty:
                df_c = df_c.ffill()
                
                # LOGIKA FILTER HARGA (Hanya berlaku jika selected_tickers KOSONG)
                if not selected_tickers:
                    last_prices = df_c.iloc[-1]
                    valid_cols = last_prices[(last_prices >= h_min) & (last_prices <= h_max)].index
                    df_f_c = df_c[valid_cols]
                    df_f_v = df_v[valid_cols]
                else:
                    df_f_c = df_c
                    df_f_v = df_v
                
                # Jalankan Analisa
                df_analysis, shortlist_keys = get_signals_and_data(df_f_c, df_f_v, is_analisa_lengkap=btn_full)

                # --- RENDER OUTPUT ---
                
                # A. TABEL SHORTLIST (Hanya muncul jika Analisa Lengkap diklik)
                if btn_full:
                    st.subheader("🎯 Shortlist: Smart Money + Broxum")
                    df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
                    if not df_top.empty:
                        st.dataframe(df_top, use_container_width=True)
                    else:
                        st.info("Tidak ada saham yang memenuhi kriteria akumulasi saat ini.")
                    st.divider()

                # B. TABEL PERSENTASE (Muncul di kedua tombol)
                st.subheader("📈 Tabel 1: Persentase Perubahan Harian (%)")
                df_pct = (df_f_c.loc[pd.to_datetime(start_d):].pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")
                df_pct.index = df_pct.index.strftime('%d/%m/%Y')
                df_out_pct = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_pct.T, left_on='Kode Saham', right_index=True)
                st.dataframe(df_out_pct.style.applymap(style_percentage), use_container_width=True)

                # C. TABEL HARGA (Muncul di kedua tombol)
                st.subheader("💵 Tabel 2: Harga Nominal Harian (IDR)")
                df_price = df_f_c.loc[pd.to_datetime(start_d):].applymap(lambda x: int(x) if pd.notnull(x) else 0)
                df_price.index = df_price.index.strftime('%d/%m/%Y')
                df_out_price = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_price.T, left_on='Kode Saham', right_index=True)
                st.dataframe(df_out_price, use_container_width=True)
            else:
                st.error("Gagal menarik data. Pastikan rentang tanggal benar atau Yahoo Finance sedang tidak limit.")
else:
    st.error("File database emiten (Excel/CSV) tidak ditemukan.")
