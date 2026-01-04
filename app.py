import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

st.set_page_config(page_title="Monitor Saham BEI Ultra", layout="wide")
st.title("🎯 Dashboard Akumulasi & Market Control")

# --- 1. FITUR CACHE ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    df = yf.download(tickers, start=start_date, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

# --- 2. LOAD DATA ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

df_emiten, nama_file_aktif = load_data_auto()

# --- 3. FUNGSI WARNA & STYLE ---
def style_control(val):
    try:
        num = float(val.replace('%', ''))
        if num > 75: return 'background-color: #ff4b4b; color: white; font-weight: bold' # Ultra Control
        if num > 50: return 'background-color: #ffa500; color: black' # Strong Control
    except: pass
    return ''

# --- 4. LOGIKA ANALISA & VOLUME CONTROL ---
def get_signals_and_data(df_c, df_v):
    results = []
    shortlist_keys = []
    
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 5: continue
        
        chg_today = (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        ticker = col.replace('.JK','')
        
        # Teori Volume Control: Persentase dominasi volume hari ini terhadap rata-rata
        # Kita gunakan rasio pertumbuhan volume sebagai proksi 'Control'
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100 
        
        status = "Normal"
        if abs(chg_5d) < 0.02 and v_ratio >= 1.5:
            status = f"💎 Akumulasi (V:{v_ratio:.1f})"
            if abs(chg_today) <= 0.01:
                shortlist_keys.append(ticker)
        elif chg_5d > 0.05 and v_ratio > 1.0:
            status = f"🚀 Markup (V:{v_ratio:.1f})"
            
        results.append({
            'Kode Saham': ticker,
            'Analisa Akumulasi': status,
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Total Lot': f"{int(v_last/100):,}"
        })
        
    return pd.DataFrame(results), shortlist_keys

# --- 5. SIDEBAR & RENDER ---
if df_emiten is not None:
    st.sidebar.header("Filter")
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=sorted(df_emiten['Kode Saham'].dropna().unique().tolist()))
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=300)
    
    today = date.today()
    start_d = st.sidebar.date_input("Mulai", today - timedelta(days=20))
    end_d = st.sidebar.date_input("Akhir", today)

    if st.sidebar.button("🚀 Jalankan Analisa Ultra"):
        with st.spinner('Menganalisa Dominasi Smart Money...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].dropna().unique()]
            
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c_raw.empty:
                df_c, df_v = df_c_raw.ffill(), df_v_raw.fillna(0)
                last_p = df_c.iloc[-1]
                saham_lolos = df_c.columns if selected_tickers else last_p[(last_p >= min_p) & (last_p <= max_p)].index
                
                df_f_c, df_f_v = df_c[saham_lolos], df_v[saham_lolos]
                df_analysis, shortlist_keys = get_signals_and_data(df_f_c, df_f_v)

                def prepare_display(df_data, is_pct=True):
                    if is_pct:
                        df_f = (df_data.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0%")
                    else:
                        df_f = df_data.applymap(lambda x: int(x) if pd.notnull(x) else 0)
                    df_f.index = df_f.index.strftime('%d/%m/%Y')
                    df_t = df_f.T
                    df_t.index = df_t.index.str.replace('.JK', '', regex=False)
                    m = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_t, left_on='Kode Saham', right_index=True)
                    f = pd.merge(m, df_analysis, on='Kode Saham', how='left')
                    # Susun kolom agar Vol Control terlihat jelas di depan
                    cols = list(f.columns)
                    return f[[cols[0], cols[1], cols[-3], cols[-2], cols[-1]] + cols[2:-3]]

                df_all_pct = prepare_display(df_f_c, is_pct=True)
                df_all_prc = prepare_display(df_f_c, is_pct=False)
                df_top = df_all_pct[df_all_pct['Kode Saham'].isin(shortlist_keys)]

                # RENDER TAMPILAN
                st.subheader("🎯 Shortlist: Akumulasi & High Control")
                if not df_top.empty:
                    st.dataframe(df_top.style.applymap(style_control, subset=['Vol Control (%)']), use_container_width=True)
                else:
                    st.warning("Tidak ada saham dengan kriteria Ultra Control.")

                st.markdown("---")
                st.subheader("📈 Monitor Persentase & Dominasi")
                st.dataframe(df_all_pct.style.applymap(style_control, subset=['Vol Control (%)']), use_container_width=True)
                
                st.subheader("💰 Monitor Harga IDR")
                st.dataframe(df_all_prc, use_container_width=True)
            else: st.error("Koneksi gagal.")
