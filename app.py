import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Strategic Top 5 Screener", layout="wide")
st.title("🏆 Strategic Moving Average: Top 5 Selection")
st.markdown("Screener ini menggunakan aturan khusus MA5, MA20, MA50, dan Free Float < 40%.")

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

# --- 2. UTIL: FORMAT TANGGAL ---
def format_id_date(ts):
    if pd.isna(ts): return "-"
    bulan = {1:"Jan", 2:"Feb", 3:"Mar", 4:"Apr", 5:"Mei", 6:"Jun", 
             7:"Jul", 8:"Agu", 9:"Sep", 10:"Okt", 11:"Nov", 12:"Des"}
    return f"{ts.day} {bulan[ts.month]} {ts.year}"

# --- 3. LOGIKA ANALISA PARAMETER BARU & RANKING ---
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
            
            # --- DATA TEKNIKAL (H-0) ---
            price = float(df_analisa['Close'].iloc[-1])
            vol = float(df_analisa['Volume'].iloc[-1])
            
            # Filter Harga Sidebar + Rules: Price > 50
            if not (min_price_input <= price <= max_price_input and price > 50):
                continue

            # --- PERHITUNGAN MOVING AVERAGE ---
            ma5 = df_analisa['Close'].rolling(5).mean().iloc[-1]
            ma20 = df_analisa['Close'].rolling(20).mean().iloc[-1]
            ma50 = df_analisa['Close'].rolling(50).mean().iloc[-1]
            
            vol_ma5 = df_analisa['Volume'].rolling(5).mean().iloc[-1]
            vol_ma20 = df_analisa['Volume'].rolling(20).mean().iloc[-1]

            # --- AMBIL INFO FREE FLOAT ---
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            ff_pct = (info.get('floatShares', 0) / info.get('sharesOutstanding', 1) * 100) if info.get('sharesOutstanding') else 100
            
            # --- EVALUASI RULES SESUAI PERMINTAAN ---
            r1 = vol_ma5 > 50000
            r2 = price <= (1.01 * ma20)
            r3 = ma20 >= (1.0 * ma50)
            r4 = price >= (0.98 * ma50)
            r5 = vol_ma5 < (1.0 * vol_ma20)
            r6 = ff_pct < 40
            r7 = ma5 < (1.0 * ma20)

            if all([r1, r2, r3, r4, r5, r6, r7]):
                # --- BACKTEST: MENCARI DAILY PROFIT TERTINGGI ---
                future_rows = saham_data.loc[(saham_data.index > end_analisa_ts) & (saham_data.index <= limit_date_ts)].copy()
                
                max_daily_pct = 0
                peak_date = None
                
                if not future_rows.empty:
                    # Daily Move = (High Hari Ini - Close Kemarin) / Close Kemarin
                    prev_closes = [price] + future_rows['Close'].shift(1).iloc[1:].tolist()
                    future_rows['Daily_Move'] = ((future_rows['High'] - prev_closes) / prev_closes) * 100
                    
                    max_daily_pct = future_rows['Daily_Move'].max()
                    peak_date = future_rows['Daily_Move'].idxmax()

                vol_ratio = vol / vol_ma5 # Digunakan untuk ranking
                results.append({
                    'Ticker': ticker.replace('.JK',''),
                    'Score': vol_ratio, 
                    'Price': round(price, 0),
                    'Vol Ratio': round(vol_ratio, 2),
                    'Free Float (%)': round(ff_pct, 1),
                    'Max Daily Move': f"{max_daily_pct:.2f}%",
                    'Peak Date': format_id_date(peak_date),
                    'Result': "Success" if max_daily_pct >= 15 else "Fail"
                })
        except: continue

    df_res = pd.DataFrame(results)
    return df_res.sort_values('Score', ascending=False) if not df_res.empty else df_res

# --- 4. UI & MAIN ---
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
        with st.spinner("Mengevaluasi parameter MA & Kelangkaan Saham..."):
            df_raw = fetch_stock_data(all_tickers, start_d, end_d)
            df_res = run_custom_analysis(df_raw, all_tickers, end_d, min_p, max_p)
            
            if not df_res.empty:
                st.subheader("🏆 The Golden 5 (Strategic Accumulation)")
                st.markdown("Saham-saham yang baru saja bangun dengan volume di bawah rata-rata bulanan.")
                
                top_5 = df_res.head(5)
                st.dataframe(top_5.drop(columns=['Score']), use_container_width=True, hide_index=True)
                
                wr_5 = (len(top_5[top_5['Result'] == "Success"]) / len(top_5)) * 100
                st.metric("Win Rate Top 5 (Daily Move > 15%)", f"{wr_5:.1f}%")

                st.divider()
                with st.expander("Lihat Semua Saham Lolos Filter"):
                    st.dataframe(df_res.drop(columns=['Score']), use_container_width=True, hide_index=True)
            else:
                st.warning("Tidak ada saham yang memenuhi kriteria kombinasi MA dan Free Float tersebut.")
else:
    st.error("File emiten tidak ditemukan. Pastikan 'Kode Saham.xlsx' ada di folder aplikasi.")
