import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Top Pick & Backtest Precision", layout="wide")
st.title("💎 Momentum Screener + High Precision Backtest")

# --- 1. FUNGSI FETCH HARGA AWAL (QUICK FILTER) ---
def get_current_prices(tickers, target_date):
    try:
        data = yf.download(tickers, start=target_date - timedelta(days=5), end=target_date + timedelta(days=1), threads=True, progress=False)
        if data.empty: return pd.Series()
        if isinstance(data.columns, pd.MultiIndex):
            return data['Close'].ffill().iloc[-1]
        return data['Close'].ffill().iloc[-1]
    except:
        return pd.Series()

# --- 2. FUNGSI FETCH DATA LENGKAP ---
@st.cache_data(ttl=3600)
def fetch_full_data(tickers, start_analisa, end_analisa):
    ext_start = start_analisa - timedelta(days=365)
    backtest_end = end_analisa + timedelta(days=50) # Buffer untuk pastikan dapet 30 hari bursa
    try:
        df = yf.download(list(tickers), start=ext_start, end=backtest_end, threads=True, progress=False)
        return df
    except:
        return pd.DataFrame()

# --- 3. LOGIKA ANALISA & BACKTEST TARGET ---
def run_analysis_and_backtest(df_full, tickers, end_analisa):
    results = []
    end_analisa_ts = pd.Timestamp(end_analisa)
    
    for ticker in tickers:
        try:
            if isinstance(df_full.columns, pd.MultiIndex):
                saham_data = df_full.xs(ticker, level=1, axis=1).dropna()
            else:
                saham_data = df_full.dropna()

            if saham_data.empty: continue

            # Data Analisa & Data Forward (30 hari bursa setelahnya)
            df_analisa = saham_data.loc[:end_analisa_ts]
            df_backtest = saham_data.loc[end_analisa_ts:].iloc[1:31] 

            if len(df_analisa) < 35 or df_backtest.empty: continue

            # Indikator Dasar
            c = df_analisa['Close']
            v = df_analisa['Volume']
            rsi = float(ta.rsi(c, length=14).iloc[-1])
            macd = ta.macd(c)
            macd_h = float(macd.filter(like='MACDh').iloc[-1]) if macd is not None else 0
            ma20 = c.rolling(20).mean().iloc[-1]
            price_buy = float(c.iloc[-1])
            v_ratio = float(v.iloc[-1] / v.rolling(20).mean().iloc[-1])
            turnover = v.iloc[-1] * price_buy

            # Kriteria Top Pick
            is_top = (55 < rsi < 72) and (macd_h > 0) and (price_buy > ma20) and (v_ratio > 2.5) and (turnover > 2_000_000_000)
            status = "💎 TOP PICK" if is_top else "Watchlist"

            # --- LOGIKA BACKTEST BARU ---
            # Hitung profit harian berdasarkan harga HIGH di masa depan
            df_backtest['Daily_Profit_Pct'] = ((df_backtest['High'] - price_buy) / price_buy) * 100
            
            # Cari kenaikan tertinggi
            max_profit = df_backtest['Daily_Profit_Pct'].max()
            
            # Cari tanggal saat kenaikan tertinggi itu terjadi
            # idxmax() akan mengembalikan index (tanggal) dari nilai tertinggi
            date_max_profit = df_backtest['Daily_Profit_Pct'].idxmax()
            
            backtest_res = "Success" if max_profit >= 10 else "Fail"
            
            # Format tanggal untuk tampilan (YYYY-MM-DD)
            display_date = date_max_profit.strftime('%Y-%m-%d') if max_profit >= 10 else "-"
            display_pct = f"{max_profit:.2f}%"

            results.append({
                'Kode Saham': ticker.replace('.JK',''),
                'Status': status,
                'Last Price': int(price_buy),
                'Backtest Result': backtest_res,
                'Date': display_date,           # Kolom baru 1
                'Percentage': display_pct,      # Kolom baru 2
                'Vol Ratio': round(v_ratio, 2),
                'RSI (14)': round(rsi, 2),
                'Turnover (M)': round(turnover / 1_000_000_000, 2)
            })
        except:
            continue
            
    df_final = pd.DataFrame(results)
    if not df_final.empty:
        df_final = df_final.sort_values(by='Vol Ratio', ascending=False)
    return df_final

# --- 4. MAIN APP ---
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
    start_d = st.sidebar.date_input("Mulai", date(2024, 10, 1))
    end_d = st.sidebar.date_input("Akhir", date(2024, 10, 31))

    if st.sidebar.button("🚀 Jalankan Analisa & Backtest"):
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]
        
        with st.spinner('Menyaring harga pasar...'):
            current_prices = get_current_prices(all_tickers, end_d)
            saham_lolos = current_prices[(current_prices >= min_p) & (current_prices <= max_p)].index.tolist()
            
        if saham_lolos:
            st.info(f"Menganalisa {len(saham_lolos)} saham. Mencari profit puncak dalam 30 hari ke depan...")
            with st.spinner('Memproses Data...'):
                df_full = fetch_full_data(saham_lolos, start_d, end_d)
                if not df_full.empty:
                    df_res = run_analysis_and_backtest(df_full, saham_lolos, end_d)
                    
                    st.subheader("🎯 Top Pick & Peak Profit Analysis")
                    df_top = df_res[df_res['Status'] == "💎 TOP PICK"]
                    st.dataframe(df_top, use_container_width=True)
                    
                    if not df_top.empty:
                        win_rate = (len(df_top[df_top['Backtest Result'] == "Success"]) / len(df_top)) * 100
                        st.metric("Win Rate Top Pick (Target 10%)", f"{win_rate:.1f}%")

                    st.divider()
                    st.subheader("📊 Semua Hasil (Urut Vol Ratio)")
                    st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Tidak ada saham yang sesuai kriteria harga.")
else:
    st.error("File database tidak ditemukan.")
