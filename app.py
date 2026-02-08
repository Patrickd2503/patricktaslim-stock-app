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
    # Buffer data untuk perhitungan indikator (Source 1 & 2) 
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(list(tickers) + ["^JKSE"], start=extended_start, end=end_date, threads=True, progress=False)
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
    # Mencari file database lokal [cite: 3, 30]
    POSSIBLE_FILES = ['FreeFloat.xlsx', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                df = pd.read_excel(file_name)
                df.columns = df.columns.str.strip()
                if 'Kode Saham' in df.columns:
                    df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK', '', regex=False)
                return df, file_name
            except: continue
    
    # Default jika file tidak ditemukan [cite: 5]
    return pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN'], 'Free Float': [30.0, 45.0, 20.0]}), "Default Mode"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI EXPORT (PILIHAN REPORT) ---
def generate_excel_report(report_type, df_short, df_all, df_c):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if report_type == "MFI & Big Volume (Source 1)":
            # Struktur Source 1 [cite: 13]
            df_short.to_excel(writer, index=False, sheet_name='Shortlist')
            df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
        else:
            # Struktur Source 2 [cite: 34]
            df_short.to_excel(writer, index=False, sheet_name='1. Shortlist Terpilih')
            df_all.to_excel(writer, index=False, sheet_name='2. Data Analisa')
            # Menambahkan histori persentase 
            df_pct = (df_c.pct_change() * 100).tail(20)
            df_pct.to_excel(writer, index=True, sheet_name='3. Histori 20D Pct')
            
    return output.getvalue()

# --- 4. LOGIKA ANALISA ---

# ANALISA 1: MFI & VOLUME (Source 1)
def run_analysis_v1(df_c, df_v, df_h, df_l, df_ref, min_vol_lot):
    results, shortlist = [], []
    ihsg_c = df_c["^JKSE"].dropna() if "^JKSE" in df_c.columns else pd.Series()
    ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0

    for col in df_c.columns:
        if col == "^JKSE" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        # Kalkulasi MFI [cite: 15, 16]
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        last_mfi = 100 - (100 / (1 + (pos_mf / neg_mf))).iloc[-1] if not neg_mf.empty and neg_mf.iloc[-1] != 0 else 50.0
        
        # Kondisi Filter [cite: 17, 18]
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        is_above_ma20 = "YA" if c.iloc[-1] > ma20 else "TIDAK"
        
        pva = "Neutral"
        if p_change > 0.5 and v.iloc[-1] > v_sma20: pva = "Bullish Vol"
        elif p_change < -0.5 and v.iloc[-1] > v_sma20: pva = "Bearish Vol"

        ticker_name = str(col).replace('.JK','').upper()
        if pva == "Bullish Vol" and is_above_ma20 == "YA" and last_mfi < 65:
            shortlist.append(ticker_name)

        results.append({
            'Kode Saham': ticker_name,
            'MFI (14D)': float(last_mfi),
            'PVA': pva,
            'Above MA20': is_above_ma20,
            'Last Price': int(c.iloc[-1]),
            'Vol/SMA20': float(v.iloc[-1] / v_sma20) if v_sma20 > 0 else 0.0
        })
    return pd.DataFrame(results), shortlist

# ANALISA 2: ARA & HISTORI (Source 2)
def run_analysis_v2(df_c, df_v):
    results, shortlist = [], []
    for col in df_c.columns:
        if col == "^JKSE": continue
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 252: continue
        
        # Kalkulasi ARA Potential [cite: 35, 36]
        daily_changes = c.pct_change() * 100
        max_daily_gain = daily_changes.tail(252).max()
        count_ara = (daily_changes.tail(252) > 20).sum()
        
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v.iloc[-1] / v_sma5 if v_sma5 > 0 else 0
        ticker = str(col).replace('.JK','')
        
        if v_ratio >= 1.5 and c.iloc[-1] > c.iloc[-2]:
            shortlist.append(ticker)

        results.append({
            'Kode Saham': ticker,
            'Max Daily Gain (12M)': f"{max_daily_gain:.1f}%",
            'Frekuensi >20% (12M)': f"{int(count_ara)}x",
            'Vol Ratio (vs SMA5)': round(v_ratio, 2),
            'Last Price': int(c.iloc[-1])
        })
    return pd.DataFrame(results), shortlist

# --- 5. UI SIDEBAR ---
st.sidebar.header("⚙️ Konfigurasi")
mode_analisa = st.sidebar.selectbox("Pilih Logika Analisa:", ["MFI & Big Volume (Source 1)", "ARA & Histori 12M (Source 2)"])

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham:", options=target_list)

min_p = st.sidebar.number_input("Harga Minimal", value=50)
max_p = st.sidebar.number_input("Harga Maksimal", value=20000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=10000)

start_d = st.sidebar.date_input("Tanggal Mulai", date.today() - timedelta(days=30))
end_d = st.sidebar.date_input("Tanggal Akhir", date.today())

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

# --- 6. PROSES & OUTPUT ---
if btn_analisa:
    with st.spinner('Menganalisa data...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            # Menjalankan logika sesuai pilihan [cite: 22, 45]
            if mode_analisa == "MFI & Big Volume (Source 1)":
                df_res, shortlist = run_analysis_v1(df_c, df_v, df_h, df_l, df_emiten, min_vol_lot)
            else:
                df_res, shortlist = run_analysis_v2(df_c, df_v)
            
            # Filter Harga
            df_res = df_res[(df_res['Last Price'] >= min_p) & (df_res['Last Price'] <= max_p)]
            df_s = df_res[df_res['Kode Saham'].isin(shortlist)]

            # Tampilkan Hasil di UI
            st.subheader(f"🎯 Shortlist: {mode_analisa}")
            st.dataframe(df_s, use_container_width=True)
            
            st.subheader("🔍 Seluruh Hasil Analisa")
            st.dataframe(df_res, use_container_width=True)

            # --- BAGIAN DOWNLOAD (SESUAI PERMINTAAN PILIHAN REPORT) ---
            st.sidebar.markdown("---")
            st.sidebar.subheader("📥 Download Report")
            
            # Pengguna bisa memilih tipe report yang ingin ditarik
            report_choice = st.sidebar.radio("Pilih Format File:", ["MFI & Big Volume (Source 1)", "ARA & Histori 12M (Source 2)"])
            
            excel_data = generate_excel_report(report_choice, df_s, df_res, df_c)
            
            st.sidebar.download_button(
                label=f"Download {report_choice}",
                data=excel_data,
                file_name=f"Report_{report_choice.replace(' ', '_')}_{date.today()}.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )
        else:
            st.error("Data tidak ditemukan.")
else:
    st.info(f"Database dimuat: {loaded_file}. Pilih parameter dan klik Jalankan Analisa.")
