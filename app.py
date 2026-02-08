import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO

# --- 1. FUNGSI STYLE (PEWARNAAN CELL) ---
def style_percentage(val):
    if pd.isna(val) or val == "": return ""
    try:
        if val > 0: return 'background-color: #2ecc71; color: white' # Hijau
        elif val < 0: return 'background-color: #e74c3c; color: white' # Merah
        else: return 'background-color: #f1c40f; color: black' # Kuning
    except: return ""

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")
st.title("🎯 Dashboard Akumulasi: Smart Money Monitor")

# --- 2. FITUR CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        mask = (df.index.date >= start_date) & (df.index.date <= end_date)
        df_filtered = df.loc[mask]
        
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low'], df_filtered['Close']
        else:
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']], df_filtered[['Close']]
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 3. LOAD DATABASE ---
def load_data_auto():
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
    return pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN']}), "Default Mode"

df_emiten, loaded_file = load_data_auto()

# --- 4. LOGIKA ANALISA GABUNGAN ---
def run_full_analysis(df_c_all, df_v, df_h, df_l, mode_source, min_p, max_p, is_custom):
    results = []
    shortlist_keys = []
    
    for col in df_c_all.columns:
        if col == "^JKSE" or pd.isna(col): continue
        c, v, h, l = df_c_all[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        last_price = c.iloc[-1]
        # Bypass filter harga jika saham dipilih secara manual
        if not is_custom:
            if not (min_p <= last_price <= max_p): continue

        ticker = str(col).replace('.JK','')
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v.iloc[-1] / v_sma5 if v_sma5 > 0 else 0
        
        # MFI (Source 1)
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        mfi_val = 100 - (100 / (1 + (pos_mf / neg_mf))).iloc[-1] if not neg_mf.empty and neg_mf.iloc[-1] != 0 else 50.0

        # ARA & Vol Control (Source 2 & 3)
        daily_pct = c.pct_change() * 100
        max_g = daily_pct.tail(252).max()
        count_ara = (daily_pct.tail(252) > 20).sum()
        vol_control = (v_ratio / (v_ratio + 1)) * 100

        # Logika Shortlist Sesuai Wording Source
        if mode_source == "Source 1: MFI & Big Volume (12 Jan)":
            if last_price > ma20 and mfi_val < 65 and v_ratio > 1.3: shortlist_keys.append(ticker)
        elif mode_source == "Source 2: ARA & Histori 12M (7 Jan)":
            if count_ara > 0 and v_ratio > 1.2: shortlist_keys.append(ticker)
        else: # Source 3
            if vol_control > 70 and last_price > c.iloc[-2]: shortlist_keys.append(ticker)

        results.append({
            'Kode Saham': ticker, 'Last Price': int(last_price),
            'MFI (14D)': round(mfi_val, 2), 'Vol Control (%)': f"{vol_control:.1f}%",
            'Freq ARA': int(count_ara), 'Vol Ratio': round(v_ratio, 2)
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. SIDEBAR ---
st.sidebar.header("⚙️ Konfigurasi")

# WORDING SOURCE LENGKAP
pilih_source = st.sidebar.selectbox(
    "Pilih Sumber Analisa:", 
    [
        "Source 1: MFI & Big Volume (12 Jan)", 
        "Source 2: ARA & Histori 12M (7 Jan)", 
        "Source 3: Split View Akumulasi (5 Jan)"
    ]
)

# OPSI TIMEFRAME
timeframe = st.sidebar.radio("View Timeframe:", ["Daily", "Weekly"], horizontal=True)

col_p1, col_p2 = st.sidebar.columns(2)
with col_p1: min_price = st.number_input("Harga Min", value=50, step=50)
with col_p2: max_price = st.number_input("Harga Max", value=10000, step=100)

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (Bypass Filter):", options=target_list)

start_d = st.sidebar.date_input("Mulai", date(2025, 10, 1))
end_d = st.sidebar.date_input("Akhir", date(2025, 12, 31))

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

# --- 6. OUTPUT ---
if btn_analisa:
    with st.spinner(f'Memproses {timeframe} data...'):
        is_custom = True if selected_tickers else False
        active_list = selected_tickers if is_custom else target_list
        tickers_jk = [t + ".JK" for t in active_list]
        
        df_c_all, df_v, df_h, df_l, df_c_filt = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c_filt.empty:
            # Resampling jika Weekly
            if timeframe == "Weekly":
                df_view_price = df_c_filt.resample('W-FRI').last()
            else:
                df_view_price = df_c_filt.copy()

            df_res, shortlist = run_full_analysis(df_c_all, df_v, df_h, df_l, pilih_source, min_price, max_price, is_custom)
            
            tab_an, tab_pct, tab_prc = st.tabs(["📊 Analisa", f"📈 {timeframe} %", f"💰 {timeframe} Harga"])
            
            with tab_an:
                st.subheader(f"🎯 Shortlist ({pilih_source})")
                st.dataframe(df_res[df_res['Kode Saham'].isin(shortlist)], use_container_width=True)
            
            with tab_pct:
                st.subheader(f"📈 Histori {timeframe} (%)")
                df_pct_view = (df_view_price.pct_change() * 100)
                df_pct_view.index = df_pct_view.index.strftime('%d/%m/%Y')
                
                st.dataframe(
                    df_pct_view.T.style.applymap(style_percentage)
                    .format("{:.2f}%", na_rep="-"), 
                    use_container_width=True
                )
                
            with tab_prc:
                st.subheader(f"💰 Histori {timeframe} (IDR)")
                df_prc_view = df_view_price.copy()
                df_prc_view.index = df_prc_view.index.strftime('%d/%m/%Y')
                st.dataframe(df_prc_view.T.style.format("{:,.0f}"), use_container_width=True)

            # EXPORT
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_res.to_excel(writer, index=False, sheet_name='Analisa')
                df_pct_view.to_excel(writer, sheet_name='Histori_Persentase')
            
            st.sidebar.download_button("📥 Download Report", data=output.getvalue(), file_name=f"Report_{timeframe}_{start_d}.xlsx")
        else:
            st.error("Data tidak ditemukan.")
else:
    st.info(f"Database aktif: {loaded_file}")
