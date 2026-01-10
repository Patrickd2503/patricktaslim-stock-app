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
    # Ambil data IHSG sebagai benchmark (^JKSE)
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) # Buffer untuk MA200 & MFI
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume'], df['High'], df['Low']
    except:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 3. FUNGSI PEWARNAAN ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white' 
        if num <= 30: return 'background-color: #008000; color: white' 
    except: pass
    return ''

def style_trend(val):
    if val == "Diatas MA20": return 'color: #008000; font-weight: bold'
    if val == "Dibawah MA20": return 'color: #ff4b4b'
    return ''

# --- 5. LOGIKA ANALISA (Update: MA20 & Relative Strength) ---
def get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    
    # Ambil data IHSG untuk Relative Strength
    ihsg_c = df_c['^JKSE'].dropna()
    ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) > 20 else 0

    for col in df_c.columns:
        if col == "^JKSE": continue
        
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        # --- [A] MONEY FLOW INDEX (MFI) ---
        typical_price = (h + l + c) / 3
        money_flow = typical_price * v
        pos_flow = (money_flow.where(typical_price > typical_price.shift(1), 0)).rolling(14).sum()
        neg_flow = (money_flow.where(typical_price < typical_price.shift(1), 0)).rolling(14).sum()
        mfi = 100 - (100 / (1 + (pos_flow / neg_flow)))
        last_mfi = mfi.iloc[-1] if not mfi.isna().iloc[-1] else 50

        # --- [B] MA20 TREND ANALYSIS ---
        ma20 = c.rolling(20).mean().iloc[-1]
        last_price = c.iloc[-1]
        trend_status = "Diatas MA20" if last_price > ma20 else "Dibawah MA20"

        # --- [C] RELATIVE STRENGTH (RS) ---
        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20]
        # Jika performa saham > performa IHSG dlm 20 hari terakhir
        rs_status = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        # --- [D] PRICE VOLUME ANALYSIS (PVA) ---
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        
        pva_status = "Neutral"
        if p_change > 1 and v_last > v_sma20: pva_status = "Bullish Vol"
        elif p_change < -1 and v_last > v_sma20: pva_status = "Bearish Vol"
        elif abs(p_change) < 1 and v_last > v_sma20: pva_status = "Churning"

        # --- [E] SHORT SWING SHORTLIST LOGIC ---
        # Kriteria: Akumulasi + Trend Naik + MFI belum panas + Lebih kuat dari Market
        if is_analisa_lengkap:
            if pva_status == "Bullish Vol" and last_mfi < 50 and trend_status == "Diatas MA20":
                shortlist_keys.append(str(col).replace('.JK',''))

        results.append({
            'Kode Saham': str(col).replace('.JK',''),
            'Tren (MA20)': trend_status,
            'MFI (14D)': round(last_mfi, 1),
            'PVA': pva_status,
            'Market RS': rs_status,
            'Price': int(last_price),
            'Vol/SMA20': round(v_last / v_sma20, 2) if v_sma20 > 0 else 0
        })
    return pd.DataFrame(results), shortlist_keys

# --- 6. RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=10000)
    start_d = st.sidebar.date_input("Mulai", date(2026, 1, 5)) 
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 10))

    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa Swing")

    if btn_analisa:
        with st.spinner('Menganalisa Tren & Money Flow...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c.empty:
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                    df_h.columns = df_h.columns.get_level_values(1)
                    df_l.columns = df_l.columns.get_level_values(1)

                df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=True)
                
                # Final Filtering
                df_analysis = df_analysis[(df_analysis['Price'] >= min_p) & (df_analysis['Price'] <= max_p)]

                st.subheader("🏁 Rekomendasi Short Swing (2 Minggu)")
                
                # TAMPILAN SHORTLIST
                st.write("### 💎 Golden Setup (MA20 Up + MFI < 50 + Bullish PVA)")
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)].sort_values(by='MFI (14D)')
                
                if not df_top.empty:
                    st.dataframe(df_top.style.applymap(style_mfi, subset=['MFI (14D)'])
                                         .applymap(style_trend, subset=['Tren (MA20)']), 
                                 use_container_width=True)
                    st.success(f"Ditemukan {len(df_top)} saham potensial. Fokus pada yang 'Outperform' terhadap Market.")
                else:
                    st.warning("Belum ada saham memenuhi kriteria Golden Setup. Coba cek tabel di bawah untuk spekulasi MFI rendah.")
                
                st.divider()
                st.write("### 📊 Monitor Seluruh Emiten")
                st.dataframe(df_analysis.style.applymap(style_mfi, subset=['MFI (14D)'])
                                         .applymap(style_trend, subset=['Tren (MA20)']), 
                             use_container_width=True)
else:
    st.error("Database tidak ditemukan.")
