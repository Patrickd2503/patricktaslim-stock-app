import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v14", layout="wide")
st.title("🎯 Dashboard Akumulasi: Smart Money Monitor (Gemini Screener 7 + Free Float GitHub)")

# --- 1. FITUR CACHE ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    extended_start = start_date - timedelta(days=365)
    try:
        df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        return df['Close'], df['Volume']
    except:
        return pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATA EMITEN ---
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

# --- 3. LOAD FREE FLOAT DARI GITHUB ---
@st.cache_data(ttl=86400)
def load_free_float_from_github():
    # Ganti URL di bawah dengan raw link GitHub kamu
    url = "https://raw.githubusercontent.com/username/repo/main/FreeFloat.xlsx"
    try:
        df_ff = pd.read_excel(url)
        return df_ff
    except:
        st.error("Gagal membaca FreeFloat.xlsx dari GitHub. Pastikan URL raw benar.")
        return None

df_ff = load_free_float_from_github()

# --- 4. EXPORT EXCEL ---
def export_to_excel(df_top, df_all):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df_top is not None and not df_top.empty:
            df_top.to_excel(writer, index=False, sheet_name='1. Top 5 Shortlist')
        df_all.to_excel(writer, index=False, sheet_name='2. Semua Hasil')
    return output.getvalue()

# --- 5. GEMINI SCREENER 7 LOGIC ---
def get_signals_and_data(df_c, df_v, df_ff=None):
    results = []
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

        # Ambil free float dari file GitHub
        ff_pct = None
        if df_ff is not None and ticker in df_ff['Kode Saham'].values:
            ff_pct = df_ff.loc[df_ff['Kode Saham'] == ticker, 'Free Float (%)'].values[0]

        # --- GEMINI SCREENER 7 FILTER ---
        cond_price = price > 50
        cond_vol = v_ma5 > 50000
        cond_ma20 = price <= 1.01 * p_ma20
        cond_ma50_up = price >= p_ma50
        cond_ma50_near = price >= 0.98 * p_ma50
        cond_vol_ratio = v_ma5 > v_ma20
        cond_ff = ff_pct is not None and ff_pct < 40
        cond_pma5 = p_ma5 < p_ma20

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
                'Free Float (%)': f"{ff_pct:.2f}%" if ff_pct else "N/A"
            })

    df_all = pd.DataFrame(results)
    if not df_all.empty:
        df_all = df_all.sort_values(by='Rasio Vol (MA5/MA20)', ascending=False)
        df_top = df_all.head(5)
    else:
        df_top = pd.DataFrame()
    return df_all, df_top

# --- 6. RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=all_tickers)

    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2025, 12, 31))

    btn_run = st.sidebar.button("🚀 Jalankan Screener Gemini 7")

    if btn_run:
        with st.spinner('Menarik data histori...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].unique()]
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

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

                # Tombol Download
                excel_data = export_to_excel(df_top, df_all)
                st.download_button(label="📥 Download Hasil ke Excel",
                                   data=excel_data,
                                   file_name=f"Gemini_Screener7_{end_d}.xlsx")
else:
    st.error("Database tidak ditemukan.")
