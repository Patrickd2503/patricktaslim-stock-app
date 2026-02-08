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

# --- 1. FITUR CACHE DATA (Gabungan Source 1, 2, 3) ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Mengambil buffer data cukup untuk indikator (MFI & ARA 12M) [cite: 14, 28]
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
    # Mencari file database lokal sesuai referensi kode [cite: 3, 30, 54]
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

# --- 3. FUNGSI EXPORT KOMBINASI (Fitur Utama Request Anda) ---
def generate_combined_report(report_choice, df_short, df_all, df_c):
    """Menggabungkan fitur report dari ketiga file sumber [cite: 13, 34, 59]"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        
        # Format Report 1: MFI & Big Volume (Source 12 Jan) 
        if report_choice == "MFI & Big Volume":
            df_short.to_excel(writer, index=False, sheet_name='Shortlist MFI')
            df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
        
        # Format Report 2: ARA & Histori 12M (Source 7 Jan) 
        elif report_choice == "ARA & Histori 12M":
            df_short.to_excel(writer, index=False, sheet_name='1. Shortlist Terpilih')
            df_all.to_excel(writer, index=False, sheet_name='2. Data Analisa')
            # Tambahan Histori Persentase [cite: 46]
            df_pct = (df_c.pct_change() * 100).tail(20)
            df_pct.to_excel(writer, index=True, sheet_name='3. Histori 20D Pct')
            
        # Format Report 3: Akumulasi & Price Action (Source 5 Jan) 
        elif report_choice == "Split View (Raw Data)":
            df_pct = (df_c.pct_change() * 100).tail(30)
            df_pct.to_excel(writer, index=True, sheet_name='Persentase Harian')
            df_c.tail(30).to_excel(writer, index=True, sheet_name='Harga Nominal IDR')
            
    return output.getvalue()

# --- 4. LOGIKA ANALISA ---
def run_full_analysis(df_c, df_v, df_h, df_l, df_ref):
    results = []
    shortlist_mfi = []
    shortlist_acc = []
    
    # Hitung IHSG Perf untuk Market RS [cite: 14]
    ihsg_c = df_c["^JKSE"].dropna() if "^JKSE" in df_c.columns else pd.Series()
    ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0

    for col in df_c.columns:
        if col == "^JKSE" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        # Indikator MFI (Source 1) [cite: 15, 16]
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        last_mfi = 100 - (100 / (1 + (pos_mf / neg_mf))).iloc[-1] if not neg_mf.empty and neg_mf.iloc[-1] != 0 else 50.0
        
        # Indikator ARA & Vol Control (Source 2 & 3) [cite: 36, 61]
        daily_changes = c.pct_change() * 100
        max_gain_12m = daily_changes.tail(252).max()
        count_ara = (daily_changes.tail(252) > 20).sum()
        
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_ratio = v.iloc[-1] / v_sma20 if v_sma20 > 0 else 0
        
        # Penentuan Status
        ticker = str(col).replace('.JK','')
        is_above_ma20 = "YA" if c.iloc[-1] > ma20 else "TIDAK"
        p_change = daily_changes.iloc[-1]
        
        pva = "Neutral"
        if p_change > 0.5 and v.iloc[-1] > v_sma20: pva = "Bullish Vol" [cite: 17]
        
        # Shortlist Logic [cite: 18, 39]
        if pva == "Bullish Vol" and is_above_ma20 == "YA" and last_mfi < 65:
            shortlist_mfi.append(ticker)
        
        results.append({
            'Kode Saham': ticker,
            'Last Price': int(c.iloc[-1]),
            'MFI (14D)': round(last_mfi, 2),
            'PVA': pva,
            'Above MA20': is_above_ma20,
            'Max Gain (12M)': f"{max_gain_12m:.1f}%",
            'Freq ARA': int(count_ara),
            'Vol Ratio': round(v_ratio, 2)
        })
        
    return pd.DataFrame(results), shortlist_mfi

# --- 5. UI & RENDER ---
st.sidebar.header("⚙️ Konfigurasi Analisa")
target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham:", options=target_list)

start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=30)) [cite: 21]
end_d = st.sidebar.date_input("Akhir", date.today())

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

if btn_analisa:
    with st.spinner('Memproses data...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_res, shortlist_keys = run_full_analysis(df_c, df_v, df_h, df_l, df_emiten)
            
            st.subheader("🎯 Shortlist (MFI & Big Volume)")
            df_s = df_res[df_res['Kode Saham'].isin(shortlist_keys)]
            st.dataframe(df_s, use_container_width=True)
            
            st.subheader("🔍 Semua Hasil Analisa")
            st.dataframe(df_res, use_container_width=True)

            # --- BAGIAN PENARIKAN REPORT (DOWNLOAD) ---
            st.sidebar.markdown("---")
            st.sidebar.subheader("📥 Penarikan Report")
            
            report_type = st.sidebar.radio(
                "Pilih Jenis Report:",
                ["MFI & Big Volume", "ARA & Histori 12M", "Split View (Raw Data)"]
            )
            
            excel_file = generate_combined_report(report_type, df_s, df_res, df_c)
            
            st.sidebar.download_button(
                label=f"📥 Download {report_type}",
                data=excel_file,
                file_name=f"Report_{report_type.replace(' ', '_')}_{date.today()}.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )
        else:
            st.error("Data tidak ditemukan.")
else:
    st.info(f"Database aktif: {loaded_file}")
