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
def run_custom_analysis(df_full, tickers, end_analisa):
    results = []
    end_analisa_ts = pd.Timestamp(end_analisa)
    limit_date_ts = end_analisa_ts + timedelta(days=30)

    for ticker in tickers:
        try:
            # Akses data ticker
            if len(tickers) > 1:
                saham_data = df_full[ticker].dropna()
            else:
                saham_data = df_full.dropna()

            if len(saham_data) < 60: continue

            # Data Hari Analisa (T-0)
            df_analisa = saham_data.loc[:end_analisa_ts]
            if df_analisa.empty: continue
            
            # --- AMBIL INFO FREE FLOAT ---
            # Catatan: Jika yfinance gagal tarik data fundamental, kita asumsikan 100 agar terfilter keluar
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            shares_outstanding = info.get('sharesOutstanding')
            float_shares = info.get('floatShares')
            
            free_float_pct = (float_shares / shares_outstanding * 100) if float_shares and shares_outstanding else 100
            
            # --- PARAMETER HARGA & VOLUME ---
            price = float(df_analisa['Close'].iloc[-1])
            vol = float(df_analisa['Volume'].iloc[-1])
            
            ma20 = df_analisa['Close'].rolling(20).mean().iloc[-1]
            ma50 = df_analisa['Close'].rolling(50).mean().iloc[-1]
            vol_ma5 = df_analisa['Volume'].rolling(5).mean().iloc[-1]

            # --- EVALUASI RULES (Sesuai Permintaan) ---
            r1 = price > 50
            r2 = vol_ma5 > 50000
            r3 = price <= (1.01 * ma20)
            r4 = ma20 >= (1.0 * ma50)
            r5 = price >= (0.98 * ma50)
            r6 = vol > (1.2 * vol_ma5)
            r7 = free_float_pct < 40

            # Jika Lolos Semua Kriteria
            if all([r1, r2, r3, r4, r5, r6, r7]):
                # Backtest 30 Hari (Cari Kenaikan Tertinggi)
                future_rows = saham_data.loc[(saham_data.index > end_analisa_ts) & (saham_data.index <= limit_date_ts)]
                peak_pct = 0
                if not future_rows.empty:
                    peak_pct = ((future_rows['High'].max() - price) / price) * 100

                # Score untuk Ranking (Prioritas Volume Ratio)
                vol_ratio = vol / vol_ma5
                score = vol_ratio 

                results.append({
                    'Ticker': ticker.replace('.JK',''),
                    'Score': score,
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
    # Urutkan berdasarkan Score (Vol Ratio) tertinggi
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
        st.header("Setting")
        start_d = st.date_input("Start Data", date(2025, 1, 1))
        end_d = st.date_input("Tanggal Analisa (H-0)", date(2025, 6, 30))
        btn = st.button("🚀 Jalankan Analisa", use_container_width=True)

    if btn:
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]
        with st.spinner("Memproses data fundamental & teknikal..."):
            df_raw = fetch_stock_data(all_tickers, start_d, end_d)
            df_res = run_custom_analysis(df_raw, all_tickers, end_d)
            
            if not df_res.empty:
                # --- BAGIAN TOP 5 ---
                st.subheader("🏆 The Golden 5 (High Conviction)")
                st.markdown("5 saham terbaik yang lolos filter dengan ledakan volume (Vol Ratio) tertinggi.")
                
                top_5 = df_res.head(5)
                st.dataframe(top_5.drop(columns=['Score']), use_container_width=True, hide_index=True)
                
                # Metric Performa Top 5
                wr_5 = (len(top_5[top_5['Result'] == "Success"]) / len(top_5)) * 100
                st.metric("Win Rate (Top 5)", f"{wr_5:.1f}%")

                st.divider()

                # --- SEMUA HASIL ---
                with st.expander("Lihat Semua Saham yang Lolos Filter"):
                    st.dataframe(df_res.drop(columns=['Score']), use_container_width=True, hide_index=True)
            else:
                st.warning("Tidak ada saham yang memenuhi semua kriteria: Price > 50, Vol MA5 > 50rb, Price dekat MA20, MA20 > MA50, dan Free Float < 40%.")
else:
    st.error("File emiten ('Kode Saham.xlsx') tidak ditemukan.")
