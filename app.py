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

# --- 1. FITUR CACHE DATA (Terpadu) ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Buffer data 12 bulan untuk analisa histori ARA dan MFI [cite: 81, 108]
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
    POSSIBLE_FILES = ['FreeFloat.xlsx', 'Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.xlsx - Sheet1.csv'] [cite: 110]
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name) [cite: 110]
                df.columns = df.columns.str.strip()
                if 'Kode Saham' in df.columns:
                    df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK', '', regex=False) [cite: 83]
                return df, file_name
            except: continue
    return pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN'], 'Free Float': [30.0, 45.0, 20.0]}), "Default Mode" [cite: 85]

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI EXPORT (Pilihan Report Lengkap) ---
def generate_combined_report(report_choice, df_short, df_all, df_c):
    """Fungsi penarikan report sesuai pilihan user """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        
        if report_choice == "MFI & Big Volume":
            df_short.to_excel(writer, index=False, sheet_name='Shortlist MFI')
            df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
        
        elif report_choice == "ARA & Histori 12M":
            df_short.to_excel(writer, index=False, sheet_name='1. Shortlist Terpilih')
            df_all.to_excel(writer, index=False, sheet_name='2. Data Analisa')
            # Tambahkan histori 20 hari terakhir
            df_pct = (df_c.pct_change() * 100).tail(20)
            df_pct.to_excel(writer, index=True, sheet_name='3. Histori 20D Pct')
            
        elif report_choice == "Split View (Persentase & Harga)": [cite: 138, 152]
            # Menghasilkan report histori harian lengkap (Source 3)
            df_pct_full = (df_c.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%") [cite: 126]
            df_pct_full.to_excel(writer, index=True, sheet_name='1. Persentase Harian')
            df_c.to_excel(writer, index=True, sheet_name='2. Harga Nominal IDR')
            if not df_short.empty:
                df_short.to_excel(writer, index=False, sheet_name='3. Shortlist')
            
    return output.getvalue()

# --- 4. LOGIKA ANALISA GABUNGAN ---
def run_integrated_analysis(df_c, df_v, df_h, df_l, df_ref):
    results = []
    shortlist_keys = []
    
    ihsg_c = df_c["^JKSE"].dropna() if "^JKSE" in df_c.columns else pd.Series()
    ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0 [cite: 94]

    for col in df_c.columns:
        if col == "^JKSE" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        # Logika MFI (Source 1) [cite: 95, 96]
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        last_mfi = 100 - (100 / (1 + (pos_mf / neg_mf))).iloc[-1] if not neg_mf.empty and neg_mf.iloc[-1] != 0 else 50.0
        
        # Logika ARA & Histori (Source 2) [cite: 115, 116]
        lookback_12m = c.iloc[-252:] if len(c) >= 252 else c
        daily_changes = lookback_12m.pct_change() * 100
        max_gain_12m = daily_changes.max()
        count_ara = (daily_changes > 20).sum()
        
        # Logika Volume Control (Source 3) [cite: 117, 141]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v.iloc[-1] / v_sma5 if v_sma5 > 0 else 0
        vol_control = (v_ratio / (v_ratio + 1)) * 100
        
        ma20 = c.rolling(20).mean().iloc[-1]
        ticker = str(col).replace('.JK','')
        is_above_ma20 = "YA" if c.iloc[-1] > ma20 else "TIDAK" [cite: 97]
        
        # Masuk Shortlist jika Bullish & MFI rendah [cite: 98]
        if c.iloc[-1] > c.iloc[-2] and is_above_ma20 == "YA" and last_mfi < 65:
            shortlist_keys.append(ticker)
        
        results.append({
            'Kode Saham': ticker,
            'Last Price': int(c.iloc[-1]),
            'MFI (14D)': round(last_mfi, 2),
            'Vol Control (%)': f"{vol_control:.1f}%",
            'Max Gain (12M)': f"{max_gain_12m:.1f}%",
            'Freq ARA': int(count_ara),
            'Above MA20': is_above_ma20,
            'Vol Ratio': round(v_ratio, 2)
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. UI & RENDER ---
st.sidebar.header("⚙️ Konfigurasi")
target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham:", options=target_list)

start_d = st.sidebar.date_input("Mulai Analisa", date.today() - timedelta(days=30)) [cite: 101]
end_d = st.sidebar.date_input("Akhir Analisa", date.today())

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA GABUNGAN", use_container_width=True)

if btn_analisa:
    with st.spinner('Memproses analisa dan data histori...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d) [cite: 102]
        
        if not df_c.empty:
            df_res, shortlist = run_integrated_analysis(df_c, df_v, df_h, df_l, df_emiten)
            df_s = df_res[df_res['Kode Saham'].isin(shortlist)]
            
            # --- TAMPILAN UI ---
            st.subheader("🎯 Shortlist (MFI & Accumulation)")
            st.dataframe(df_s, use_container_width=True)
            
            # FITUR REQUEST: Split View Persentase di UI [cite: 129, 130, 153, 154]
            tab1, tab2, tab3 = st.tabs(["📊 Semua Analisa", "📈 Split View Persentase (%)", "💰 Split View Harga (IDR)"])
            
            with tab1:
                st.dataframe(df_res, use_container_width=True)
                
            with tab2:
                df_pct_view = (df_c.pct_change() * 100).tail(15)
                df_pct_view.index = df_pct_view.index.strftime('%d/%m/%Y')
                st.dataframe(df_pct_view.T.style.format("{:.2f}%"), use_container_width=True)
                
            with tab3:
                df_price_view = df_c.tail(15)
                df_price_view.index = df_price_view.index.strftime('%d/%m/%Y')
                st.dataframe(df_price_view.T, use_container_width=True)

            # --- PENARIKAN DATA (DOWNLOAD) ---
            st.sidebar.markdown("---")
            st.sidebar.subheader("📥 Penarikan Report")
            
            report_type = st.sidebar.radio(
                "Pilih Format Laporan Excel:",
                ["MFI & Big Volume", "ARA & Histori 12M", "Split View (Persentase & Harga)"]
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
            st.error("Data tidak ditemukan untuk periode tersebut.")
else:
    st.info(f"Database emiten dimuat: {loaded_file}. Klik tombol untuk memulai.")
