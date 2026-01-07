import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Top Pick Backtest - Peak Closing", layout="wide")
st.title("💎 Momentum Screener & Peak Closing Backtest")

# --- 1. FUNGSI FETCH HARGA AWAL ---
def get_current_prices(tickers, target_date):
    try:
        data = yf.download(
            tickers,
            start=target_date - timedelta(days=7),
            end=target_date + timedelta(days=2),
            auto_adjust=True,
            threads=True,
            progress=False
        )
        if data.empty:
            return pd.Series(dtype=float)
        return data['Close'].ffill().iloc[-1]
    except Exception:
        return pd.Series(dtype=float)

# --- 2. FUNGSI FETCH DATA LENGKAP ---
def fetch_full_data(tickers, start_analisa, end_analisa):
    ext_start = start_analisa - timedelta(days=365)
    backtest_end = end_analisa + timedelta(days=60)  # buffer 60 hari
    try:
        df = yf.download(
            list(tickers),
            start=ext_start,
            end=backtest_end,
            auto_adjust=True,
            threads=True,
            progress=False
        )
        return df
    except Exception:
        return pd.DataFrame()

# --- 3. FORMAT TANGGAL INDONESIA ---
def format_id_date(ts):
    bulan = {
        1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
        5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
        9: "September", 10: "Oktober", 11: "November", 12: "Desember"
    }
    return f"{ts.day} {bulan[ts.month]} {ts.year}"

# --- 4. UTIL: BAND ARA BEI ---
def ara_band(close_price):
    # Aturan umum BEI (disederhanakan):
    if close_price < 200:
        return 35.0
    elif close_price <= 5000:
        return 25.0
    else:
        return 20.0

# --- 5. LOGIKA ANALISA & BACKTEST (DAILY MOVE) ---
def run_analysis_and_backtest(df_full, tickers, end_analisa):
    results = []
    end_analisa_ts = pd.Timestamp(end_analisa)

    for ticker in tickers:
        try:
            # Ambil data untuk ticker
            if isinstance(df_full.columns, pd.MultiIndex):
                saham_data = df_full.xs(ticker, level=1, axis=1).dropna()
            else:
                saham_data = df_full.dropna()

            if saham_data.empty or 'Close' not in saham_data.columns:
                continue

            # Hari beli = first trading day setelah end_analisa
            future_rows = saham_data.loc[saham_data.index > end_analisa_ts]
            if future_rows.empty:
                continue

            buy_row = future_rows.iloc[0]
            buy_date = future_rows.index[0]
            price_buy = float(buy_row['Close'])

            # Jendela backtest: 30 hari trading setelah tanggal beli
            df_backtest = future_rows.loc[future_rows.index > buy_date].head(30).copy()
            if df_backtest.empty:
                continue

            # Hitung daily move (% dari hari sebelumnya)
            df_backtest['Prev_Close'] = df_backtest['Close'].shift(1)
            df_backtest['Daily_Move'] = ((df_backtest['Close'] - df_backtest['Prev_Close']) / df_backtest['Prev_Close']) * 100

            # Cari hari pertama yang mencapai batas ARA sesuai band harga
            ara_date = None
            ara_pct = None
            for idx, row in df_backtest.iterrows():
                if pd.isna(row['Prev_Close']):
                    continue
                band = ara_band(row['Prev_Close'])
                day_move = (row['Close'] - row['Prev_Close']) / row['Prev_Close'] * 100
                if day_move >= band:
                    ara_date = idx
                    ara_pct = band
                    break  # ambil tanggal pertama kali ARA

            # Jika tidak ada ARA, ambil daily move tertinggi
            if ara_date is None:
                max_idx = df_backtest['Daily_Move'].idxmax()
                ara_date = max_idx
                ara_pct = df_backtest.loc[max_idx, 'Daily_Move']

            # Success jika pernah ada ARA >=10% (atau sesuai band)
            backtest_res = "Success" if ara_pct >= 10 else "Fail"

            display_date = format_id_date(ara_date)
            display_pct = f"{ara_pct:.2f}%"

            results.append({
                'Kode Saham': ticker.replace('.JK',''),
                'Last Price': round(price_buy, 2),
                'Backtest Result': backtest_res,
                'Date': display_date,
                'Percentage': display_pct
            })
        except Exception:
            continue

    return pd.DataFrame(results)

# --- 6. MAIN APP ---
def load_emiten():
    for f in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(f):
            df = pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)
            df.columns = [c.strip() for c in df.columns]
            return df
    return None

df_emiten = load_emiten()

if df_emiten is not None:
    st.sidebar.header("Filter Parameter")
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=2000)

    st.sidebar.subheader("Periode Analisa")
    start_d = st.sidebar.date_input("Mulai Analisa", date(2025, 5, 1))
    end_d = st.sidebar.date_input("Akhir Analisa (Beli)", date(2025, 5, 31))

    if st.sidebar.button("🚀 Jalankan Analisa & Backtest"):
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]

        with st.spinner('Menyinkronkan harga beli (Closing)...'):
            current_prices = get_current_prices(all_tickers, end_d)
            saham_lolos = current_prices[(current_prices >= min_p) & (current_prices <= max_p)].index.tolist()

        if saham_lolos:
            st.info(f"Menganalisa {len(saham_lolos)} saham. Mencari puncak daily move (30 hari)...")
            with st.spinner('Memproses perhitungan sesuai skenario...'):
                df_full = fetch_full_data(saham_lolos, start_d, end_d)
                if not df_full.empty:
                    df_res = run_analysis_and_backtest(df_full, saham_lolos, end_d)

                    st.subheader("🎯 Top Pick & Daily ARA Analysis")
                    st.dataframe(df_res, use_container_width=True)

                    if not df_res.empty:
                        win_rate = (len(df_res[df_res['Backtest Result'] == "Success"]) / len(df_res)) * 100
                        st.metric("Win Rate", f"{win_rate:.1f}%")
        else:
            st.warning("Tidak ada saham yang ditemukan.")
else:
    st.error("File database tidak ditemukan.")
