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
    # Buffer data untuk analisa histori ARA dan MFI [cite: 81, 108]
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

# --- 2. LOAD DATABASE EMITEN ---
def load_data_auto():
    # Mencari file database lokal [cite: 110, 134]
    POSSIBLE_FILES = ['FreeFloat.xlsx', 'Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.xlsx - Sheet1.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)
                df.columns = df.columns.str.strip()
                if 'Kode Saham' in df.columns:
                    df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK', '', regex=False)
                return df, file_name
            except: continue
    return pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN'], 'Free Float': [30.0, 45.0, 20.0]}), "Default Mode"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI EXPORT ---
def generate_combined_report(df_s, df_res, df_c):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_s.to_excel(writer, index=False, sheet_name='Shortlist')
        df_res.to_excel(writer, index=False, sheet_name='Semua Analisa')
        # Split View: Persentase Harian [cite: 114, 139]
        df_pct = (df_c.pct_change() * 100).tail(20)
        df_pct.to_excel(writer, index=True, sheet_name='Histori_Pct')
    return output.getvalue()

# --- 4. LOGIKA ANALISA GABUNGAN ---
def run_analysis(df_c, df_v, df_h, df_l, mode):
    results = []
    shortlist_keys = []
    
    for col in df_c.columns:
        if col == "^JKSE" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        ticker = str(col).replace('.JK','')
        ma20 = c.rolling(20).mean().iloc[-1]
        
        # LOGIKA SOURCE 1: MFI & PVA [cite: 96, 97]
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        mfi = 100 - (100 / (1 + (pos_mf / neg_mf))).iloc[-1] if not neg_mf.empty and neg_mf.iloc[-1] != 0 else 50.0
        
        # LOGIKA SOURCE 2: ARA & VOL CONTROL [cite: 116, 117]
        daily_changes = c.pct_change() * 100
        max_gain = daily_changes.tail(252).max()
        count_ara = (daily_changes.tail(252) > 20).sum()
        v_ratio = v.iloc[-1] / v.rolling(5).mean().iloc[-1] if len(v) > 5 else 0
        
        # Filter Shortlist berdasarkan Mode yang dipilih
        if mode == "MFI & Big Volume (Source 1)":
            if c.iloc[-1] > ma20 and mfi < 65 and v_ratio > 1.2:
                shortlist_keys.append(ticker)
        else: # ARA Mode
            if count_ara > 0 and v_ratio > 1.5:
                shortlist_keys.append(ticker)

        results.append({
            'Kode Saham': ticker,
            'Last Price': int(c.iloc[-1]),
            'MFI (14D)': round(mfi, 2),
            'Max Gain (12M)': f"{max_gain:.1f}%",
            'Freq ARA': int(count_ara),
            'Vol Ratio': round(v_ratio, 2),
            'Above MA20': "YA" if c.iloc[-1] > ma20 else "TIDAK"
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. UI SIDEBAR (PILIHAN SOURCE) ---
st.sidebar.header("⚙️ Konfigurasi")

# INTEGRASI KEMBALI: Pilihan Logika Analisa
source_mode = st.sidebar.selectbox(
    "Pilih Logika Analisa:",
    ["MFI & Big Volume (Source 1)", "ARA & Histori 12M (Source 2)"]
)

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham:", options=target_list)

start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=30))
end_d = st.sidebar.date_input("Akhir", date.today())

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

# --- 6. RENDER OUTPUT ---
if btn_analisa:
    with st.spinner(f'Menganalisa menggunakan {source_mode}...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_res, shortlist = run_analysis(df_c, df_v, df_h, df_l, source_mode)
            df_s = df_res[df_res['Kode Saham'].isin(shortlist)]
            
            tab1, tab2, tab3 = st.tabs(["📊 Analisa", "📈 Split View (%)", "💰 Split View Harga"])
            
            with tab1:
                st.subheader(f"🎯 Shortlist: {source_mode}")
                st.dataframe(df_s, use_container_width=True)
                st.subheader("🔍 Semua Data")
                st.dataframe(df_res, use_container_width=True)
                
            with tab2:
                # Split View Persentase [cite: 126, 149]
                df_pct_view = (df_c.pct_change() * 100).tail(15)
                df_pct_view.index = df_pct_view.index.strftime('%d/%m/%Y')
                st.dataframe(df_pct_view.T.style.format("{:.2f}%"), use_container_width=True)
                
            with tab3:
                # Split View Harga [cite: 130, 154]
                df_price_view = df_c.tail(15)
                df_price_view.index = df_price_view.index.strftime('%d/%m/%Y')
                st.dataframe(df_price_view.T, use_container_width=True)

            # Download Report
            excel_file = generate_combined_report(df_s, df_res, df_c)
            st.sidebar.download_button(
                label="📥 Download Report Excel",
                data=excel_file,
                file_name=f"Report_{source_mode[:5]}_{date.today()}.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )
else:
    st.info(f"Database aktif: {loaded_file}")
