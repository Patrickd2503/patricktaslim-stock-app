import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v3 Longgar", layout="wide")
st.title("🎯 Dashboard Akumulasi v3 – Kriteria Longgar")

# --- 1. CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    extended_start = start_date - timedelta(days=100)  # Untuk MA akurat
    df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

@st.cache_data(ttl=86400)
def get_free_float(ticker_jk):
    try:
        info = yf.Ticker(ticker_jk).info
        f_shares = info.get('floatShares')
        total_s = info.get('sharesOutstanding')
        if f_shares and total_s: return (f_shares / total_s) * 100
    except: pass
    return None

# --- 2. LOAD DATA ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

df_emiten, _ = load_data_auto()

# --- 3. STYLE ---
def style_control(val):
    try:
        num = float(str(val).replace('%', '').replace(',', '.'))
        if num > 70: return 'background-color: #ff4b4b; color: white; font-weight: bold'
        if num > 65: return 'background-color: #ff6b6b; color: white'
        if num > 50: return 'background-color: #ffa500; color: black'
    except: pass
    return ''

def style_float(val):
    try:
        num = float(str(val).replace('%', '').replace(',', '.'))
        if num < 45: return 'color: #008000; font-weight: bold'
    except: pass
    return ''

def style_percentage(val):
    try:
        num_val = float(str(val).replace('%', '').replace(',', '.'))
        if num_val > 0: return 'background-color: rgba(144, 238, 144, 0.4)'
        elif num_val < 0: return 'background-color: rgba(255, 182, 193, 0.4)'
        elif num_val == 0: return 'background-color: rgba(255, 255, 0, 0.3)'
    except: pass
    return ''

# --- 4. EXPORT ---
def export_to_excel(df_pct, df_prc, df_top=None):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if df_top is not None and not df_top.empty:
            df_top.to_excel(writer, index=False, sheet_name='1. Shortlist Terpilih')
        df_pct.to_excel(writer, index=False, sheet_name='2. Data Persentase')
        df_prc.to_excel(writer, index=False, sheet_name='3. Data Harga IDR')
    return output.getvalue()

# --- 5. LOGIKA ANALISA v3 LONGGAR ---
def get_signals_and_data(df_c, df_v, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 30: continue  # Cukup 30 hari sudah aman

        # Volume metrics
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100

        # Price metrics
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        price = c.iloc[-1]
        ticker = col.replace('.JK', '')

        status = "Normal"
        ff_pct = None

        if is_analisa_lengkap:
            ff_pct = get_free_float(col)

            # Deteksi Akumulasi (sama seperti sebelumnya)
            if abs(chg_5d) < 0.02 and v_ratio >= 1.2:
                status = f"💎 Akumulasi (V:{v_ratio:.1f}x)"

            # KRITERIA SHORTLIST YANG DILONGGARKAN
            if (status.startswith("💎") and
                vol_control_pct > 65 and                                          # Turun dari 70
                (ff_pct < 45 if ff_pct is not None else False) and                # Naik dari 40
                v_sma5 / 100 >= 300 and                                           # Rata-rata 300 lot (30.000 saham)
                v_last >= 1.1 * v_ma20):                                           # Volume hari ini naik dari MA20
                shortlist_keys.append(ticker)

            if chg_5d > 0.05:
                status = "🚀 Markup"

        results.append({
            'Kode Saham': ticker,
            'Analisa Akumulasi': status,
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Free Float (%)': f"{ff_pct:.1f}%" if ff_pct else "N/A",
            'Rata Lot (5D)': f"{int(v_sma5/100):,}",
            'Total Lot (Today)': f"{int(v_last/100):,}"
        })

    return pd.DataFrame(results), shortlist_keys

# --- 6. RENDER DASHBOARD ---
if df_emiten is not None:
    st.sidebar.header("Filter & Parameter")
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=sorted(df_emiten['Kode Saham'].dropna().unique().tolist()))
    min_p = st.sidebar.number_input("Harga Min", value=50)      # Turunkan dari 100
    max_p = st.sidebar.number_input("Harga Max", value=2000)     # Naikkan dari 900
    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 5))

    st.sidebar.markdown("---")
    btn_split = st.sidebar.button("📊 1. Split View (All Data)")
    btn_analisa = st.sidebar.button("🚀 2. Jalankan Analisa Lengkap")

    if btn_split or btn_analisa:
        with st.spinner('Memproses data bursa...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].dropna().unique()]
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

            if not df_c_raw.empty:
                df_c = df_c_raw.ffill()
                df_v = df_v_raw.fillna(0)
                last_p = df_c.iloc[-1]
                saham_lolos = df_c.columns if selected_tickers else last_p[(last_p >= min_p) & (last_p <= max_p)].index
                df_f_c, df_f_v = df_c[saham_lolos], df_v[saham_lolos]

                df_analysis, shortlist_keys = get_signals_and_data(df_f_c, df_f_v, is_analisa_lengkap=btn_analisa)

                def prepare_display(df_data, is_pct=True):
                    df_view = df_data.loc[pd.to_datetime(start_d):]
                    if is_pct:
                        df_f = (df_view.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")
                    else:
                        df_f = df_view.applymap(lambda x: int(x) if pd.notnull(x) else 0)
                    df_f.index = df_f.index.strftime('%d/%m/%Y')
                    df_t = df_f.T
                    df_t.index = df_t.index.str.replace('.JK', '', regex=False)
                    m = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_t, left_on='Kode Saham', right_index=True)
                    m = pd.merge(m, df_analysis, on='Kode Saham', how='left')
                    cols = list(m.columns)
                    # Urutan: Kode, Nama, metadata, lalu histori
                    return m[[cols[0], cols[1], cols[-6], cols[-5], cols[-4], cols[-3], cols[-2], cols[-1]] + cols[2:-6]]

                df_all_pct = prepare_display(df_f_c, is_pct=True)
                df_all_prc = prepare_display(df_f_c, is_pct=False)

                if btn_split:
                    st.success("Mode Split View")
                    st.download_button("📥 Download Excel (Raw)", data=export_to_excel(df_all_pct, df_all_prc),
                                       file_name=f'Split_View_{end_d}.xlsx')
                    st.subheader("📈 Monitor Persentase Harian")
                    st.dataframe(df_all_pct.style.applymap(style_percentage, subset=df_all_pct.columns[8:]), use_container_width=True)
                    st.subheader("💰 Monitor Harga (IDR)")
                    st.dataframe(df_all_prc, use_container_width=True)

                elif btn_analisa:
                    df_top = df_all_pct[df_all_pct['Kode Saham'].isin(shortlist_keys)]
                    st.success("Analisa Selesai! Kriteria shortlist sudah dilonggarkan.")
                    st.download_button("📥 Download All to Excel", data=export_to_excel(df_all_pct, df_all_prc, df_top),
                                       file_name=f'Analisa_Longgar_{end_d}.xlsx')

                    st.subheader("🎯 Shortlist Terpilih (Akumulasi Longgar)")
                    if not df_top.empty:
                        st.dataframe(df_top.style.applymap(style_control, subset=['Vol Control (%)'])
                                     .applymap(style_float, subset=['Free Float (%)'])
                                     .applymap(style_percentage, subset=df_top.columns[8:]), use_container_width=True)
                        st.info(f"Ditemukan **{len(df_top)} saham** yang memenuhi kriteria akumulasi longgar.")
                    else:
                        st.warning("Masih belum ada saham yang lolos. Coba perluas lagi rentang harga atau periode.")

                    st.divider()
                    st.subheader("📈 Semua Data Persentase")
                    st.dataframe(df_all_pct.style.applymap(style_control, subset=['Vol Control (%)'])
                                 .applymap(style_float, subset=['Free Float (%)'])
                                 .applymap(style_percentage, subset=df_all_pct.columns[8:]), use_container_width=True)
            else:
                st.error("Data tidak ditemukan atau ticker tidak valid.")
else:
    st.error("File 'Kode Saham.xlsx' tidak ditemukan di folder ini.")
