import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
from io import BytesIO
import requests

st.set_page_config(page_title="Monitor Saham BEI Ultra v20", layout="wide")
st.title("🎯 Smart Money Monitor (Gemini Screener 7 + Free Float GitHub, 1 Tanggal Analisa)")

@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, end_date):
    # otomatis ambil 1 tahun ke belakang dari end_date
    start_date = end_date - timedelta(days=365)
    try:
        df = yf.download(tickers, start=start_date, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume']
    except:
        return pd.DataFrame(), pd.DataFrame()

def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        try:
            if file_name.endswith('.csv'):
                return pd.read_csv(file_name), file_name
            else:
                return pd.read_excel(file_name), file_name
        except:
            continue
    return None, None

df_emiten, _ = load_data_auto()

@st.cache_data(ttl=86400)
def load_free_float_from_github():
    url = "https://raw.githubusercontent.com/Patrickd2503/patricktaslim-stock-app/main/FreeFloat.xlsx"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return pd.read_excel(BytesIO(r.content))
    except Exception as e:
        st.error(f"Gagal membaca FreeFloat.xlsx dari GitHub: {e}")
        return None

df_ff = load_free_float_from_github()

def get_signals_and_data(df_c, df_v, df_ff=None):
    results = []
    ff_map = {}
    if df_ff is not None and {'Kode Saham', 'Free Float (%)'}.issubset(set(df_ff.columns)):
        ff_map = dict(zip(df_ff['Kode Saham'].astype(str).str.strip(), df_ff['Free Float (%)']))

    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 50:
            continue

        price = c.iloc[-1]
        v_ma5 = v.rolling(5).mean().iloc[-1]
        v_ma20 = v.rolling(20).mean().iloc[-1]
        p_ma5 = c.rolling(5).mean().iloc[-1]
        p_ma20 = c.rolling(20).mean().iloc[-1]
        p_ma50 = c.rolling(50).mean().iloc[-1]

        ticker = col.replace('.JK', '')
        ff_pct = ff_map.get(ticker, None)

        # --- FILTER LONGGAR ---
        cond_price = price > 50
        cond_vol = v_ma5 > 10000
        cond_ma20 = price <= 1.02 * p_ma20
        cond_ma50_up = price >= p_ma50
        cond_ma50_near = price >= 0.97 * p_ma50
        cond_vol_ratio = v_ma5 > v_ma20
        cond_ff = ff_pct is not None and ff_pct <= 45
        cond_pma5 = p_ma5 <= p_ma20

        if all([cond_price, cond_vol, cond_ma20, cond_ma50_up,
                cond_ma50_near, cond_vol_ratio, cond_ff, cond_pma5]):

            vol_ratio = v_ma5 / v_ma20 if v_ma20 > 0 else 0
            results.append({
                'Kode Saham': ticker,
                'Harga': round(price, 2),
                'Volume MA5': int(v_ma5),
                'Volume MA20': int(v_ma20),
                'Rasio Vol (MA5/MA20)': round(vol_ratio, 2),
                'Price MA20': round(p_ma20, 2),
                'Price MA50': round(p_ma50, 2),
                'Price MA5': round(p_ma5, 2),
                'Free Float (%)': f"{ff_pct:.2f}%" if ff_pct is not None else "N/A"
            })

    df_all = pd.DataFrame(results)
    df_top = pd.DataFrame()
    if not df_all.empty:
        df_all = df_all.sort_values(by='Rasio Vol (MA5/MA20)', ascending=False)
        df_top = df_all.head(5)
    return df_all, df_top

# --- RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=all_tickers)

    # hanya pilih tanggal analisa
    end_d = st.sidebar.date_input("Tanggal Analisa", date.today())

    btn_run = st.sidebar.button("🚀 Jalankan Screener Gemini 7")

    if btn_run:
        with st.spinner('Menarik data histori...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), end_d)

            if not df_c_raw.empty:
                if isinstance(df_c_raw.columns, pd.MultiIndex):
                    df_c_raw.columns = df_c_raw.columns.get_level_values(1)
                    df_v_raw.columns = df_v_raw.columns.get_level_values(1)

                df_all, df_top = get_signals_and_data(df_c_raw, df_v_raw, df_ff)

                st.subheader("🎯 Top 5 Saham (Rasio Volume Tertinggi)")
                if not df_top.empty:
                    st.dataframe(df_top, use_container_width=True)
                else:
                    st.info("Tidak ada saham yang lolos filter Gemini Screener 7.")

                st.divider()
                st.subheader("📈 Semua Saham Lolos Screener")
                st.dataframe(df_all, use_container_width=True)

                excel_data = export_to_excel(df_top, df_all)
                st.download_button(label="📥 Download Hasil ke Excel",
                                   data=excel_data,
                                   file_name=f"Gemini_Screener7_{end_d}.xlsx")
else:
    st.error("Database tidak ditemukan.")
