import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Strategic Top 5 Screener", layout="wide")
st.title("🏆 Strategic Moving Average: Top 5 Selection")
st.markdown("Screener ini menyaring saham berdasarkan parameter MA & Free Float, lalu memberikan **Ranking 5 Terbaik**.")

# --- 1. FUNGSI FETCH DATA HARGA ---
def fetch_stock_data(tickers, start_analisa, end_analisa):
    # Buffer 150 hari agar perhitungan MA50 akurat
    ext_start = start_analisa - timedelta(days=150) 
    backtest_end = end_analisa + timedelta(days=45) 
    try:
        df = yf.download(
            list(tickers),
            start=ext_start,
            end=backtest_end,
            auto_adjust=True,
            threads=True,
            group_by='ticker',
            progress=False
        )
        return df
    except Exception:
        return pd.DataFrame()

# --- 2. LOGIKA ANALISA PARAMETER KHUSUS & RANKING ---
def run_custom_analysis(df_full, tickers, end_analisa, min_price_input, max_price_input):
    results = []
    end_analisa_ts = pd.Timestamp(end_analisa)
    limit_date_ts = end_analisa_ts + timedelta(days=30)

    for ticker in tickers:
        try:
            if len(tickers) > 1:
                saham_data = df_full[ticker].dropna()
            else:
                saham_data = df_full.dropna()

            if len(saham_data) < 60: continue

            df_analisa = saham_data.loc[:end_analisa_ts]
            if df_analisa.empty: continue
            
            # --- DATA TEKNIKAL ---
            price = float(df_analisa['Close'].iloc[-1])
            
            # Filter Harga dari Sidebar + Aturan Wajib Price > 50
            if not (min_price_input <= price <= max_price_input and price > 50):
                continue

            # --- AMBIL INFO FREE FLOAT ---
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            shares_outstanding = info.get('sharesOutstanding')
            float_shares = info.get('floatShares')
            free_float_pct = (float_shares / shares_outstanding * 100) if float_shares and shares_outstanding else 100
            
            # --- PARAMETER MA & VOLUME ---
            vol = float(df_analisa['Volume'].iloc[-1])
            ma20 = df_analisa['Close'].rolling(20).mean().iloc[-1]
            ma50 = df_analisa['Close'].rolling(50).mean().iloc[-1]
            vol_ma5 = df_analisa['Volume'].rolling(5).mean().iloc[-1]

            # --- EVALUASI RULES ---
            r2 = vol_ma5 > 50000
            r3 = price <= (1.01 * ma20)
            r4 = ma20 >= (1.0 * ma50)
            r5 = price >= (0.98 * ma50)
            r6 = vol > (1.2 * vol_ma5)
            r7 = free_float_pct < 40

            if all([r2, r3, r4, r5, r6, r7]):
                # Backtest (High Price dalam 30 hari ke depan)
                future_rows = saham_data.loc[(saham_data.index > end_analisa_ts) & (saham_data.index <= limit_date_ts)]
                peak_pct = 0
                if not future_rows.empty:
                    peak_pct = ((future_rows['High'].max() - price) / price) * 100

                vol_ratio = vol / vol_ma5
                results.append({
                    'Ticker': ticker.replace('.JK',''),
                    'Score': vol_ratio, # Ranking berdasarkan ledakan volume
                    'Price': round(price, 0),
                    'Vol Ratio': round(vol_ratio, 2),
                    'Free Float (%)': round(free_float_pct, 2),
                    'MA20': round(ma20, 2),
                    'MA50': round(ma50, 2),
                    'Max Move (30D)': f"{peak_pct:.2f}%",
                    'Result': "Success" if peak_pct >= 10 else "Fail"
                })
        except: continue

    df_res = pd.DataFrame(results)
    return df_res.sort_values('Score', ascending=False) if not df_res.empty else df_res

# --- 3. UI & MAIN ---
def load_emiten():
    for f in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(f):
            df = pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)
            df.columns = [c.strip() for c in df.columns]
            return df
    return None

df_emiten = load_emiten()

if df_emiten is not None:
    with st.sidebar:
        st.header("Filter Harga")
        min_p = st.number_input("Harga Minimal", value=50)
        max_p = st.number_input("Harga Maksimal", value=5000)
        
        st.header("Periode Analisa")
        start_d = st.date_input("Start Data Historis", date(2025, 1, 1))
        end_d = st.date_input("Tanggal Analisa (H-0)", date(2025, 6, 30))
        
        btn = st.button("🚀 Jalankan Analisa", use_container_width=True)

    if btn:
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]
        with st.spinner("Memproses filter teknikal & Free Float..."):
            df_raw = fetch_stock_data(all_tickers, start_d, end_d)
            df_res = run_custom_analysis(df_raw, all_tickers, end_d, min_p, max_p)
            
            if not df_res.empty:
                st.subheader("🏆 The Golden 5 (High Conviction)")
                top_5 = df_res.head(5)
                st.dataframe(top_5.drop(columns=['Score']), use_container_width=True, hide_index=True)
                
                wr_5 = (len(top_5[top_5['Result'] == "Success"]) / len(top_5)) * 100
                st.metric("Win Rate (Top 5)", f"{wr_5:.1f}%")

                st.divider()
                with st.expander("Lihat Semua Saham Lolos Filter"):
                    st.dataframe(df_res.drop(columns=['Score']), use_container_width=True, hide_index=True)
            else:
                st.warning("Tidak ada saham yang memenuhi kriteria di rentang harga tersebut.")
else:
    st.error("File 'Kode Saham.xlsx' tidak ditemukan.")
