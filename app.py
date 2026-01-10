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
    # Buffer data diperpanjang sedikit untuk perhitungan indikator teknikal (MFI butuh 14 hari)
    extended_start = start_date - timedelta(days=400)
    try:
        df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume'], df['High'], df['Low']
    except:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=86400)
def get_free_float(ticker_jk):
    try:
        info = yf.Ticker(ticker_jk).info
        f_shares = info.get('floatShares')
        total_s = info.get('sharesOutstanding')
        if f_shares and total_s: return (f_shares / total_s) * 100
    except: pass
    return None

# --- 2. LOAD DATA ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

df_emiten, _ = load_data_auto()

# --- 3. FUNGSI PEWARNAAN ---
def style_control(val):
    try:
        num = float(str(val).replace('%', '').replace(',', '.'))
        if num > 70: return 'background-color: #ff4b4b; color: white; font-weight: bold'
        if num > 50: return 'background-color: #ffa500; color: black'
    except: pass
    return ''

def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white' # Overbought
        if num <= 20: return 'background-color: #008000; color: white' # Oversold
    except: pass
    return ''

# --- 5. LOGIKA ANALISA (Update: PVA & Money Flow Index) ---
def get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 20: continue
        
        # --- [A] MONEY FLOW INDEX (MFI) CALCULATION ---
        typical_price = (h + l + c) / 3
        money_flow = typical_price * v
        positive_flow = []
        negative_flow = []
        
        for i in range(1, len(typical_price)):
            if typical_price.iloc[i] > typical_price.iloc[i-1]:
                positive_flow.append(money_flow.iloc[i])
                negative_flow.append(0)
            elif typical_price.iloc[i] < typical_price.iloc[i-1]:
                negative_flow.append(money_flow.iloc[i])
                positive_flow.append(0)
            else:
                positive_flow.append(0)
                negative_flow.append(0)
        
        period = 14
        pos_mf_sum = pd.Series(positive_flow).rolling(window=period).sum()
        neg_mf_sum = pd.Series(negative_flow).rolling(window=period).sum()
        mfr = pos_mf_sum / neg_mf_sum
        mfi = 100 - (100 / (1 + mfr))
        last_mfi = mfi.iloc[-1] if not mfi.empty else 50

        # --- [B] PRICE VOLUME ANALYSIS (PVA) ---
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        
        pva_status = "Neutral"
        if p_change > 1 and v_last > v_sma20:
            pva_status = "Bullish Vol" # Akumulasi Kuat
        elif p_change < -1 and v_last > v_sma20:
            pva_status = "Bearish Vol" # Distribusi Panik
        elif abs(p_change) < 1 and v_last > v_sma20:
            pva_status = "Churning" # Perpindahan tangan besar di harga sama

        # --- [C] EXISTING ANALYTICS ---
        daily_changes = c.iloc[-252:].pct_change() * 100
        max_daily_gain = daily_changes.max()
        count_ara = (daily_changes > 20).sum()
        
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100 
        
        ff_pct = get_free_float(col) if is_analisa_lengkap else None
        ticker = str(col).replace('.JK','')

        # Short Swing Logic: Akumulasi + MFI Belum Overbought
        if is_analisa_lengkap:
            if pva_status == "Bullish Vol" and last_mfi < 70 and v_ratio > 1.5:
                shortlist_keys.append(ticker)

        results.append({
            'Kode Saham': ticker,
            'PVA': pva_status,
            'MFI (14D)': round(last_mfi, 1),
            'Max Gain': f"{max_daily_gain:.1f}%",
            'Freq ARA': f"{int(count_ara)}x",
            'Vol Control': f"{vol_control_pct:.1f}%",
            'Free Float': f"{ff_pct:.1f}%" if ff_pct else "N/A",
            'Vol/SMA5': round(v_ratio, 2)
        })
    return pd.DataFrame(results), shortlist_keys

# --- 6. RENDER DASHBOARD (Updated logic for MFI & PVA) ---
if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=10000)
    start_d = st.sidebar.date_input("Mulai", date(2026, 1, 5)) # Update ke Jan 2026
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 10))

    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa Smart Money")

    if btn_analisa:
        with st.spinner('Menghitung MFI & PVA...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c.empty:
                # Handle MultiIndex column fix
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                    df_h.columns = df_h.columns.get_level_values(1)
                    df_l.columns = df_l.columns.get_level_values(1)

                df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=True)
                
                # Filter by price range
                last_prices = df_c.ffill().iloc[-1]
                valid_price_tickers = last_prices[(last_prices >= min_p) & (last_prices <= max_p)].index.str.replace('.JK','')
                df_analysis = df_analysis[df_analysis['Kode Saham'].isin(valid_price_tickers)]

                st.subheader("🏁 Hasil Analisa Swing (PVA & Money Flow)")
                
                # Menampilkan Shortlist (Potensi Swing 2 Minggu)
                st.write("### 💎 Shortlist (Good PVA + Low/Mid MFI)")
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
                st.dataframe(df_top.style.applymap(style_mfi, subset=['MFI (14D)']), use_container_width=True)
                
                st.divider()
                st.write("### 📊 Semua Data")
                st.dataframe(df_analysis.style.applymap(style_mfi, subset=['MFI (14D)']), use_container_width=True)
else:
    st.error("Database tidak ditemukan.")
