import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Momentum Screener Pro", layout="wide")
st.title("💎 Momentum Screener & Daily ARA Backtest")
st.markdown("Screener ini mencari saham dengan volume spike dan menguji performanya dalam 30 hari ke depan.")

# --- 1. FUNGSI FETCH HARGA AWAL ---
def get_current_prices(tickers, target_date):
    try:
        data = yf.download(
            tickers,
            start=target_date - timedelta(days=10),
            end=target_date + timedelta(days=1),
            auto_adjust=True,
            threads=True,
            progress=False
        )
        if data.empty:
            return pd.Series(dtype=float)
        
        if isinstance(data.columns, pd.MultiIndex):
            return data['Close'].ffill().iloc[-1]
        else:
            return pd.Series({tickers[0]: data['Close'].ffill().iloc[-1]})
    except Exception:
        return pd.Series(dtype=float)

# --- 2. FUNGSI FETCH DATA LENGKAP ---
def fetch_full_data(tickers, start_analisa, end_analisa):
    ext_start = start_analisa - timedelta(days=365)
    backtest_end = end_analisa + timedelta(days=65) 
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

# --- 3. UTIL: FORMAT & ARA BAND ---
def format_id_date(ts):
    if pd.isna(ts): return "-"
    bulan = {1:"Jan", 2:"Feb", 3:"Mar", 4:"Apr", 5:"Mei", 6:"Jun", 
             7:"Jul", 8:"Agu", 9:"Sep", 10:"Okt", 11:"Nov", 12:"Des"}
    return f"{ts.day} {bulan[ts.month]} {ts.year}"

def ara_band(close_price):
    if close_price < 200: return 35.0
    elif close_price <= 5000: return 25.0
    else: return 20.0

# --- 4. LOGIKA ANALISA & BACKTEST ---
def run_analysis_and_backtest(df_full, tickers, end_analisa):
    results = []
    end_analisa_ts = pd.Timestamp(end_analisa)

    for ticker in tickers:
        try:
            # Proteksi akses data
            if len(tickers) > 1:
                saham_data = df_full[ticker].dropna()
            else:
                saham_data = df_full.dropna()

            if saham_data.empty or len(saham_data) < 35: continue

            # T-0 (Hari Analisa/Beli)
            df_analisa = saham_data.loc[:end_analisa_ts]
            if df_analisa.empty: continue
            
            # Masa Depan (Backtest 30 Bar)
            future_rows = saham_data.loc[saham_data.index > end_analisa_ts].head(31)
            if future_rows.empty: continue

            # Data Point Penting
            price_buy = float(df_analisa['Close'].iloc[-1])
            c = df_analisa['Close'].astype(float)
            v = df_analisa['Volume'].astype(float)

            # Indikator Teknikal
            rsi = float(ta.rsi(c, length=14).iloc[-1])
            macd = ta.macd(c)
            macd_h = float(macd.filter(like='MACDh').iloc[-1]) if macd is not None else 0.0
            ma20 = float(c.rolling(20).mean().iloc[-1])
            v_avg20 = v.rolling(20).mean().iloc[-1]
            v_ratio = float(v.iloc[-1] / v_avg20) if v_avg20 > 0 else 0
            turnover = float(v.iloc[-1] * price_buy)

            # --- KRITERIA OPTIMASI (TIPS: Diperlonggar agar lebih inklusif) ---
            cond_rsi = (45 < rsi < 75)
            cond_vol = (v_ratio > 1.5)
            cond_trend = (price_buy > ma20 * 0.98) # Toleransi 2% di bawah MA20
            cond_liq = (turnover > 1_000_000_000) # Min 1 Miliar

            is_top = cond_rsi and cond_vol and cond_trend and cond_liq
            status = "💎 TOP PICK" if is_top else "Watchlist"

            # Proses Backtest
            df_bt = future_rows.copy()
            df_bt['Prev_Close'] = [price_buy] + df_bt['Close'].shift(1).iloc[1:].tolist()
            df_bt['Daily_Move'] = ((df_bt['Close'] - df_bt['Prev_Close']) / df_bt['Prev_Close']) * 100

            # Cari ARA atau Peak
            peak_date, peak_pct = None, -100
            for idx, row in df_bt.iterrows():
                band = ara_band(row['Prev_Close'])
                # Deteksi ARA dengan toleransi fraksi BEI
                if row['Daily_Move'] >= (band - 0.2):
                    peak_date, peak_pct = idx, row['Daily_Move']
                    break
                if row['Daily_Move'] > peak_pct:
                    peak_date, peak_pct = idx, row['Daily_Move']

            # Success jika dalam 30 hari pernah naik > 10%
            backtest_res = "Success" if peak_pct >= 10 else "Fail"

            results.append({
                'Ticker': ticker.replace('.JK',''),
                'Status': status,
                'Buy Price': round(price_buy, 0),
                'Max Move': f"{peak_pct:.2f}%",
                'Peak Date': format_id_date(peak_date),
                'Result': backtest_res,
                'Vol Ratio': round(v_ratio, 2),
                'RSI': round(rsi, 1),
                'Turnover (M)': round(turnover / 1_000_000_000, 1)
            })
        except: continue

    return pd.DataFrame(results)

# --- 5. LOAD DATA EMITEN ---
def load_emiten():
    for f in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(f):
            df = pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)
            df.columns = [c.strip() for c in df.columns]
            return df
    return None

# --- 6. UI & MAIN LOGIC ---
df_emiten = load_emiten()

if df_emiten is not None:
    with st.sidebar:
        st.header("Konfigurasi")
        min_p = st.number_input("Harga Min", value=50)
        max_p = st.number_input("Harga Max", value=5000)
        
        st.subheader("Periode")
        start_d = st.date_input("Mulai Data Analisa", date(2024, 6, 1))
        end_d = st.date_input("Tanggal Beli (H-0)", date(2024, 12, 1))
        
        btn = st.button("🚀 Jalankan Backtest", use_container_width=True)

    if btn:
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]
        
        with st.spinner("Fetching data..."):
            prices = get_current_prices(all_tickers, end_d)
            valid_tickers = prices[(prices >= min_p) & (prices <= max_p)].index.tolist()
            
            if valid_tickers:
                df_raw = fetch_full_data(valid_tickers, start_d, end_d)
                df_final = run_analysis_and_backtest(df_raw, valid_tickers, end_d)
                
                if not df_final.empty:
                    # Metrics
                    top_df = df_final[df_final['Status'] == "💎 TOP PICK"]
                    
                    st.subheader("📈 Ringkasan Performa")
                    m1, m2, m3 = st.columns(3)
                    
                    if not top_df.empty:
                        wr = (len(top_df[top_df['Result'] == "Success"]) / len(top_df)) * 100
                        m1.metric("Top Picks Ditemukan", f"{len(top_df)} Saham")
                        m2.metric("Win Rate Top Pick", f"{wr:.1f}%")
                        m3.metric("Avg Vol Ratio", f"{top_df['Vol Ratio'].mean():.2f}x")
                    else:
                        st.info("Tidak ada Top Pick. Cobalah melonggarkan filter.")

                    st.divider()
                    
                    # Tampilan Tabel
                    st.subheader("🎯 Hasil Analisa")
                    tab1, tab2 = st.tabs(["Top Picks", "Watchlist"])
                    
                    with tab1:
                        st.dataframe(top_df.sort_values('Vol Ratio', ascending=False), 
                                     use_container_width=True, hide_index=True)
                    with tab2:
                        others = df_final[df_final['Status'] == "Watchlist"]
                        st.dataframe(others.sort_values('Vol Ratio', ascending=False), 
                                     use_container_width=True, hide_index=True)
                else:
                    st.warning("Tidak ada data yang memenuhi kriteria dasar.")
            else:
                st.error("Tidak ada saham ditemukan di rentang harga tersebut.")
else:
    st.error("File 'Kode Saham.xlsx' tidak ditemukan.")

