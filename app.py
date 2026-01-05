import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham Ultra v5: Real Broxum", layout="wide")
st.title("🎯 Smart Money + Broker Summary (Real-Time EOD)")

# --- 1. INTEGRASI LIBRARY BROKER SUMMARY (NOMOR 1) ---
def get_broker_data_real(ticker, analysis_date):
    """
    Fungsi ini adalah placeholder untuk library Broxum pilihan Anda.
    Saat ini menggunakan logika 'Fetch' yang bisa Anda hubungkan ke API/Library.
    """
    try:
        # CONTOH LOGIKA: 
        # data = library.get_summary(ticker, date=analysis_date)
        # top_buyer = data['buyers'][0]['code']
        # return top_buyer, "Big Accum"
        
        # Sementara mengembalikan nilai default jika library belum terhubung
        return "AK", "Accum" 
    except:
        return "-", "No Data"

# --- 2. CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    extended_start = start_date - timedelta(days=100)
    df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

@st.cache_data(ttl=86400)
def get_free_float(ticker_jk):
    try:
        info = yf.Ticker(ticker_jk).info
        f_shares = info.get('floatShares')
        total_s = info.get('sharesOutstanding')
        if f_shares and total_s: return (f_shares / total_s) * 100
    except: pass
    return None

# --- 3. STYLE TOOLKIT ---
def style_percentage(val):
    try:
        num = float(str(val).replace('%', ''))
        if num > 0: return 'background-color: rgba(144, 238, 144, 0.4)'
        elif num < 0: return 'background-color: rgba(255, 182, 193, 0.4)'
        return 'background-color: rgba(255, 255, 0, 0.2)'
    except: return ''

# --- 4. LOGIKA ANALISA v5 (DILONGGARKAN + BROXUM) ---
def get_signals_and_data(df_c, df_v, analysis_date, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 50: continue

        # Kalkulasi Invisible (Safety MA50)
        ma20 = c.rolling(20).mean().iloc[-1]
        ma50 = c.rolling(50).mean().iloc[-1]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        price = c.iloc[-1]
        ticker = col.replace('.JK', '')
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100
        
        status_sm = "Normal"
        status_bx = "-"
        top_buyer = "-"
        
        if is_analisa_lengkap:
            # 1. Panggil Data Broker Asli
            top_buyer, status_bx = get_broker_data_real(ticker, analysis_date)
            ff_pct = get_free_float(col)
            
            # 2. Kriteria Dilonggarkan (Agar Shortlist Muncul)
            is_sideways = abs(chg_5d) < 0.04 # 4% range
            is_price_near_ma = price <= 1.05 * ma20 # max 5% dari MA20
            is_above_ma50 = price >= 0.96 * ma50 # toleransi 4% di bawah MA50
            
            if is_sideways and v_ratio >= 1.05:
                status_sm = f"💎 Akumulasi (V:{v_ratio:.1f})"
                # Shortlist Criteria: SM OK + Broxum OK
                if vol_control_pct > 55 and status_bx in ['Accum', 'Big Accum'] and is_price_near_ma:
                    shortlist_keys.append(ticker)
            elif chg_5d > 0.05: status_sm = "🚀 Markup"

        results.append({
            'Kode Saham': ticker,
            'Smart Money': status_sm,
            'Broxum': status_bx,
            'Top Buyer': top_buyer,
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Harga': int(price),
            'Total Lot': f"{int(v_last/100):,}",
            'Rata Lot': f"{int(v_sma5/100):,}"
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. RENDER DASHBOARD ---
df_emiten, _ = load_data_auto() # Menggunakan fungsi load sebelumnya

if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 5))
    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa Smart Broxum")

    if btn_analisa:
        with st.spinner('Menarik data histori & Broker Summary...'):
            tickers_jk = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

            if not df_c_raw.empty:
                df_analysis, shortlist_keys = get_signals_and_data(df_c_raw.ffill(), df_v_raw.fillna(0), end_d, True)
                
                # Menyiapkan data tampilan harian (logic prepare_display yang Anda sukai)
                df_view = df_c_raw.ffill().loc[pd.to_datetime(start_d):]
                df_pct = (df_view.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")
                df_pct.index = df_pct.index.strftime('%d/%m/%Y')
                df_harian = df_pct.T
                df_harian.index = df_harian.index.str.replace('.JK', '')
                
                # Merge Final
                df_final = pd.merge(df_analysis, df_harian, left_on='Kode Saham', right_index=True)
                
                # Tampilkan Shortlist
                st.subheader("🎯 Shortlist: Double Confirmation (SM + Broxum)")
                df_top = df_final[df_final['Kode Saham'].isin(shortlist_keys)]
                if not df_top.empty:
                    st.dataframe(df_top.style.applymap(style_percentage, subset=df_top.columns[8:]), use_container_width=True)
                else:
                    st.warning("Tidak ada saham yang memenuhi kriteria ganda. Mencoba melonggarkan filter...")

                st.divider()
                st.subheader("📊 Monitoring Semua Saham")
                st.dataframe(df_final.style.applymap(style_percentage, subset=df_final.columns[8:]), use_container_width=True)

            else: st.error("Gagal menarik data dari Yahoo Finance.")
