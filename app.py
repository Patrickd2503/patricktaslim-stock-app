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
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume'], df['High'], df['Low']
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATABASE EMITEN ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'data.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)
                if 'Kode Saham' in df.columns:
                    return df, file_name
            except: continue
    default_data = pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN', 'STRK', 'KAEF', 'ICON', 'SPRE', 'LIVE', 'VIVA', 'BUMI', 'GOTO']})
    return default_data, "Default Mode (File Not Found)"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI STYLING & EXCEL ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white'
        if num <= 40: return 'background-color: #008000; color: white'
    except: pass
    return ''

def highlight_outperform(row):
    return ['background-color: #1e3d59; color: white' if row['Market RS'] == 'Outperform' else '' for _ in row]

def style_percentage(val):
    try:
        num_val = float(str(val).replace('%', ''))
        if num_val > 0: return 'background-color: rgba(144, 238, 144, 0.4)'
        elif num_val < 0: return 'background-color: rgba(255, 182, 193, 0.4)'
    except: pass
    return ''

def to_excel_multi_sheet(df_shortlist, df_all, df_pct, df_prc):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_shortlist.to_excel(writer, index=False, sheet_name='1. Shortlist')
        df_all.to_excel(writer, index=False, sheet_name='2. Analisa Utama')
        df_pct.to_excel(writer, index=True, sheet_name='3. Histori %')
        df_prc.to_excel(writer, index=True, sheet_name='4. Histori Harga')
    return output.getvalue()

# --- 4. LOGIKA ANALISA TEKNIKAL ---
def get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    if "^JKSE" in df_c.columns:
        ihsg_c = df_c["^JKSE"].dropna()
        ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0
    else:
        ihsg_perf = 0

    for col in df_c.columns:
        if col == "^JKSE" or col == "": continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 30: continue
        
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf)))
        last_mfi = mfi_series.iloc[-1] if not np.isnan(mfi_series.iloc[-1]) else 50
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        last_p = c.iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        trend = "Diatas MA20" if last_p > ma20 else "Dibawah MA20"
        
        pva = "Neutral"
        if p_change > 1 and v.iloc[-1] > v_sma20: pva = "Bullish Vol"
        elif p_change < -1 and v.iloc[-1] > v_sma20: pva = "Bearish Vol"
        elif abs(p_change) < 1 and v.iloc[-1] > v_sma20: pva = "Churning"

        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        if is_analisa_lengkap and pva == "Bullish Vol" and last_mfi < 55 and last_p > ma20:
            shortlist_keys.append(str(col).replace('.JK',''))

        results.append({
            'Kode Saham': str(col).replace('.JK',''),
            'Tren (MA20)': trend,
            'MFI (14D)': last_mfi,
            'PVA': pva,
            'Market RS': rs,
            'Last Price': int(last_p),
            'Vol/SMA20': v.iloc[-1] / v_sma20 if v_sma20 > 0 else 0
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. RENDER DASHBOARD ---
st.sidebar.info(f"Database: {loaded_file}")

if not df_emiten.empty:
    st.sidebar.header("⚙️ Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Pilih Kode Spesifik:", options=all_tickers)
    min_p = st.sidebar.number_input("Harga Min", value=50); max_p = st.sidebar.number_input("Harga Max", value=20000)
    start_d = st.sidebar.date_input("Mulai", date(2026, 1, 5)); end_d = st.sidebar.date_input("Akhir", date(2026, 1, 10))

    st.sidebar.markdown("---")
    show_split = st.sidebar.checkbox("📊 Aktifkan Split View (Histori)")
    btn_analisa = st.sidebar.button("🚀 Jalankan Analisa Lengkap")

    if btn_analisa:
        with st.spinner('Memproses data market...'):
            target_list = selected_tickers if selected_tickers else all_tickers
            tickers_jk = [str(k).strip() + ".JK" for k in target_list]
            df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c.empty:
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                    df_h.columns = df_h.columns.get_level_values(1)
                    df_l.columns = df_l.columns.get_level_values(1)

                df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=True)
                df_analysis = df_analysis[(df_analysis['Last Price'] >= min_p) & (df_analysis['Last Price'] <= max_p)]
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)].sort_values(by='MFI (14D)')

                # --- PREPARASI DATA SPLIT VIEW (Histori) ---
                df_hist_pct = (df_c.pct_change() * 100).dropna()
                df_hist_pct.index = df_hist_pct.index.strftime('%d/%m/%Y')
                df_hist_prc = df_c.copy()
                df_hist_prc.index = df_hist_prc.index.strftime('%d/%m/%Y')

                # TOMBOL DOWNLOAD (4 Sheets)
                excel_file = to_excel_multi_sheet(df_top, df_analysis, df_hist_pct.T, df_hist_prc.T)
                st.download_button(label="📥 Download Full Report (4 Sheets)", data=excel_file, file_name=f'Analisa_Lengkap_{end_d}.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

                # --- OUTPUT 1: GOLDEN SETUP ---
                st.subheader("💎 Golden Setup (Rekomendasi Entry Jam 10:30)")
                if not df_top.empty:
                    st.dataframe(df_top.style.apply(highlight_outperform, axis=1)
                                    .applymap(style_mfi, subset=['MFI (14D)'])
                                    .format({"MFI (14D)": "{:.1f}", "Vol/SMA20": "{:.2f}"}), use_container_width=True)
                else:
                    st.warning("Tidak ada saham yang memenuhi syarat ketat hari ini.")

                # --- OUTPUT 2: SPLIT VIEW (Hanya jika dicentang) ---
                if show_split:
                    st.divider()
                    st.subheader("📈 Monitor Persentase Histori")
                    # Format tampilan persentase untuk dashboard
                    df_disp_pct = df_hist_pct.T.applymap(lambda x: f"{x:.1f}%")
                    st.dataframe(df_disp_pct.style.applymap(style_percentage), use_container_width=True)
                    
                    st.subheader("💰 Monitor Harga Histori (IDR)")
                    st.dataframe(df_hist_prc.T, use_container_width=True)

                st.divider()
                st.write("### 📊 Monitor Seluruh Emiten")
                st.dataframe(df_analysis.style.applymap(style_mfi, subset=['MFI (14D)']).format({"MFI (14D)": "{:.1f}", "Vol/SMA20": "{:.2f}"}), use_container_width=True)
            else:
                st.error("Data tidak ditemukan.")
