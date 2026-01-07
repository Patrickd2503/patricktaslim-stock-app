import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Top Pick & Backtest Monitor", layout="wide")
st.title("💎 Momentum Screener + Backtest")

# --- 1. FUNGSI FETCH HARGA AWAL (QUICK FILTER) ---
def get_current_prices(tickers, target_date):
    try:
        # Mengambil data pada tanggal akhir periode untuk filter harga
        data = yf.download(tickers, start=target_date - timedelta(days=5), end=target_date + timedelta(days=1), threads=True, progress=False)
        if data.empty: return pd.Series()
        if isinstance(data.columns, pd.MultiIndex):
            return data['Close'].ffill().iloc[-1]
        return data['Close'].ffill().iloc[-1]
    except:
        return pd.Series()

# --- 2. FUNGSI FETCH DATA LENGKAP (HISTORI & BACKTEST) ---
@st.cache_data(ttl=3600)
def fetch_full_data(tickers, start_analisa, end_analisa):
    # Periode Analisa (Histori untuk indikator)
    ext_start = start_analisa - timedelta(days=365)
    # Periode Backtest (30 hari setelah end_analisa)
    backtest_end = end_analisa + timedelta(days=45) # 45 hari kalender asumsikan ~30 hari bursa
    
    try:
        df = yf.download(list(tickers), start=ext_start, end=backtest_end, threads=True, progress=False)
        if df.empty: return pd.DataFrame()
        return df
    except:
        return pd.DataFrame()

# --- 3. LOGIKA ANALISA & BACKTEST ---
def run_analysis_and_backtest(df_full, tickers, end_analisa):
    results = []
    
    # Pastikan end_analisa ada dalam index
    end_analisa_ts = pd.Timestamp(end_analisa)
    
    for ticker in tickers:
        try:
            # Ambil data spesifik saham
            if isinstance(df_full.columns, pd.MultiIndex):
                saham_data = df_full.xs(ticker, level=1, axis=1).dropna()
            else:
                saham_data = df_full.dropna() # Jika hanya 1 saham

            if saham_data.empty: continue

            # Potong data untuk Analisa (sampai end_analisa)
            df_analisa = saham_data.loc[:end_analisa_ts]
            # Potong data untuk Backtest (setelah end_analisa sampai 30 hari bursa)
            df_backtest = saham_data.loc[end_analisa_ts:].iloc[1:31] # 30 baris setelah hari beli

            if len(df_analisa) < 35 or df_backtest.empty: continue

            # --- HITUNG INDIKATOR ---
            c = df_analisa['Close']
            v = df_analisa['Volume']
            rsi = ta.rsi(c, length=14)
            rsi_val = float(rsi.iloc[-1]) if rsi is not None else 50
            macd = ta.macd(c)
            macd_h = float(macd.filter(like='MACDh').iloc[-1]) if macd is not None else 0
            ma20 = c.rolling(20).mean().iloc[-1]
            v_ratio = float(v.iloc[-1] / v.rolling(20).mean().iloc[-1])
            price_buy = float(c.iloc[-1]) # Harga beli (Harga penutupan hari terakhir periode)
            turnover = v.iloc[-1] * price_buy

            # --- KRITERIA TOP PICK ---
            is_top = (55 < rsi_val < 72) and (macd_h > 0) and (price_buy > ma20) and (v_ratio > 2.5) and (turnover > 2_000_000_000)
            status = "💎 TOP PICK" if is_top else "Watchlist"

            # --- LOGIKA BACKTEST (10% Profit Target) ---
            highest_after = df_backtest['High'].max()
            profit_pct = ((highest_after - price_buy) / price_buy) * 100
            backtest_res = "Success" if profit_pct >= 10 else "Fail"

            results.append({
                'Kode Saham': ticker.replace('.JK',''),
                'Status': status,
                'Last Price': int(price_buy),
                'Backtest Result': backtest_res, # Posisi di sebelah kanan Last Price
                'Max Rise (%)': round(profit_pct, 2),
                'Vol Ratio': round(v_ratio, 2),
                'RSI (14)': round(rsi_val, 2)
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
        
        with st.spinner('Memfilter harga...'):
            current_prices = get_current_prices(all_tickers, end_d)
            saham_lolos = current_prices[(current_prices >= min_p) & (current_prices <= max_p)].index.tolist()
            
        if saham_lolos:
            st.info(f"Menganalisa {len(saham_lolos)} saham. Mengecek performa 30 hari ke depan...")
            with st.spinner('Menghitung Backtest...'):
                df_full = fetch_full_data(saham_lolos, start_d, end_d)
                if not df_full.empty:
                    df_res = run_analysis_and_backtest(df_full, saham_lolos, end_d)
                    
                    # Tampilan Shortlist
                    st.subheader("🎯 Top Pick & Validasi Backtest")
                    df_top = df_res[df_res['Status'] == "💎 TOP PICK"]
                    st.dataframe(df_top, use_container_width=True)
                    
                    # Statistik sederhana
                    if not df_top.empty:
                        win_rate = (len(df_top[df_top['Backtest Result'] == "Success"]) / len(df_top)) * 100
                        st.metric("Win Rate Top Pick", f"{win_rate:.1f}%")

                    st.divider()
                    st.subheader("📊 Semua Hasil (Urut Vol Ratio)")
                    st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Tidak ada saham di rentang harga tersebut.")
else:
    st.error("File database tidak ditemukan.")
