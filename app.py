import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

st.set_page_config(page_title="Monitor Saham BEI Ultra", layout="wide")
st.title("🎯 Dashboard Akumulasi: Market Control & Free Float")

# --- 1. FITUR CACHE ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    df = yf.download(tickers, start=start_date, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

@st.cache_data(ttl=86400) # Info fundamental jarang berubah, cache 24 jam
def get_free_float(ticker_jk):
    try:
        info = yf.Ticker(ticker_jk).info
        f_shares = info.get('floatShares')
        total_s = info.get('sharesOutstanding')
        if f_shares and total_s:
            return (f_shares / total_s) * 100
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
        if num > 75: return 'background-color: #ff4b4b; color: white; font-weight: bold'
        if num > 50: return 'background-color: #ffa500; color: black'
    except: pass
    return ''

def style_float(val):
    try:
        num = float(str(val).replace('%', '').replace(',', '.'))
        if num < 40: return 'color: #008000; font-weight: bold' # Hijau jika barang sedikit
    except: pass
    return ''

# --- 4. LOGIKA ANALISA GABUNGAN ---
def get_signals_and_data(df_c, df_v):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 6: continue
        
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        ticker = col.replace('.JK','')
        
        # Ambil Free Float
        ff_pct = get_free_float(col)
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100 
        
        status = "Normal"
        # Kriteria Shortlist: Sideways + Vol Meledak + Free Float Rendah
        is_accum = abs(chg_5d) < 0.02 and v_ratio >= 1.5
        is_low_float = ff_pct is not None and ff_pct < 40
        
        if is_accum:
            status = f"💎 Akumulasi (V:{v_ratio:.1f})"
            if is_low_float: # Hanya masuk shortlist jika barang sedikit (<40%)
                shortlist_keys.append(ticker)
            
        results.append({
            'Kode Saham': ticker,
            'Analisa Akumulasi': status,
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Free Float (%)': f"{ff_pct:.1f}%" if ff_pct else "N/A",
            'Rata Lot (5D)': f"{int(v_sma5/100):,}",
            'Total Lot (Today)': f"{int(v_last/100):,}"
        })
    return pd.DataFrame(results), shortlist_keys

# --- 5. RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter")
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=sorted(df_emiten['Kode Saham'].dropna().unique().tolist()))
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=5000)
    start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=20))
    end_d = st.sidebar.date_input("Akhir", date.today())

    if st.sidebar.button("🚀 Jalankan Super Analisa"):
        with st.spinner('Menganalisis Control & Struktur Saham...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].dropna().unique()]
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c_raw.empty:
                df_c, df_v = df_c_raw.ffill(), df_v_raw.fillna(0)
                last_p = df_c.iloc[-1]
                saham_lolos = df_c.columns if selected_tickers else last_p[(last_p >= min_p) & (last_p <= max_p)].index
                df_analysis, shortlist_keys = get_signals_and_data(df_c[saham_lolos], df_v[saham_lolos])

                def apply_all_styles(df):
                    return df.style.applymap(style_control, subset=['Vol Control (%)']) \
                                   .applymap(style_float, subset=['Free Float (%)'])

                st.subheader("🎯 Shortlist: Akumulasi & Low Free Float (<40%)")
                df_top = df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)]
                if not df_top.empty: st.dataframe(apply_all_styles(df_top), use_container_width=True)
                else: st.warning("Belum ada saham dengan kombinasi Akumulasi + Low Float.")

                st.markdown("---")
                st.subheader("📈 Semua Hasil Analisa")
                st.dataframe(apply_all_styles(df_analysis), use_container_width=True)
