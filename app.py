import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Momentum Screener Pro", layout="wide")
st.title("💎 Momentum Screener & Daily ARA Backtest")
st.markdown("Screener ini membatasi jendela kenaikan maksimal **30 hari kalender** dari tanggal beli.")

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
    # Ambil buffer cukup luas, pemotongan ketat dilakukan di logika backtest
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
    # BATAS KAKU: 30 Hari Kalender dari Tanggal Beli
    limit_date_ts = end_analisa_ts + timedelta(days=30)

    for ticker in tickers:
        try:
            if len(tickers) > 1:
                saham_data = df_full[ticker].dropna()
            else:
                saham_data = df_full.dropna()

            if saham_data.empty or len(saham_data) < 35: continue

            # Data Hari Analisa (T-0)
            df_analisa = saham_data.loc[:end_analisa_ts]
            if df_analisa.empty: continue
            
            # --- PERUBAHAN DISINI: Filter Tanggal secara Kaku (Max 30 Hari Kalender) ---
            future_rows = saham_data.loc[(saham_data.index > end_analisa_ts) & 
                                         (saham_data.index <= limit_date_ts)]
            
            if future_rows.empty: continue

            price_buy = float(df_analisa['Close'].iloc[-1])
            c = df_analisa['Close'].astype(float)
            v = df_analisa['Volume'].astype(float)

            # Indikator (Filter Longgar)
            rsi = float(ta.rsi(c, length=14).iloc[-1])
            macd = ta.macd(c)
            macd_h = float(macd.filter(like='MACDh').iloc[-1]) if macd is not None else 0.0
            ma20 = float(c.rolling(20).mean().iloc[-1])
            v_avg20 = v.rolling(20).mean().iloc[-1]
            v_ratio = float(v.iloc[-1] / v_avg20) if v_avg20 > 0 else 0
            turnover = float(v.iloc[-1] * price_buy)

            # Kriteria Top Pick (Optimized)
            is_top = (45 < rsi < 75) and (v_ratio > 1.5) and (price_buy > ma20 * 0.98) and (turnover > 1_000_000_000)
            status = "💎 TOP PICK" if is_top else "Watchlist"

            # Hitung Daily Move dalam jendela 30 hari kalender
            df_bt = future_rows.copy()
            df_bt['Prev_Close'] = [price_buy] + df_bt['Close'].shift(1).iloc[1:].tolist()
            df_bt['Daily_Move'] = ((df_bt['Close'] - df_bt['Prev_Close']) / df_bt['Prev_Close']) * 100

            peak_date, peak_pct = None, -100
            for idx, row in df_bt.iterrows():
                band = ara_band(row['Prev_Close'])
                if row['Daily_Move'] >= (band - 0.2):
                    peak_date, peak_pct = idx, row['Daily_Move']
                    break
                if row['Daily_Move'] > peak_pct:
                    peak_date, peak_pct = idx, row['Daily_Move']

            # Definisi Sukses (Naik minimal 10% dalam 30 hari)
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

# --- 5. UI & LOAD DATA ---
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
        st.header("Konfigurasi")
        min_p = st.number_input("Harga Min", value=50)
        max_p = st.number_input("Harga Max", value=5000)
        st.subheader("Periode")
        start_d = st.date_input("Mulai Data Analisa", date(2025, 1, 1))
        end_d = st.date_input("Tanggal Beli (H-0)", date(2025, 6, 30))
        btn = st.button("🚀 Jalankan Backtest", use_container_width=True)

    if btn:
        all_tickers = [str(t).strip() + ".JK" for t in df_emiten['Kode Saham']]
        with st.spinner("Menganalisa..."):
            prices = get_current_prices(all_tickers, end_d)
            valid_tickers = prices[(prices >= min_p) & (prices <= max_p)].index.tolist()
            
            if valid_tickers:
                df_raw = fetch_full_data(valid_tickers, start_d, end_d)
                df_final = run_analysis_and_backtest(df_raw, valid_tickers, end_d)
                
                if not df_final.empty:
                    top_df = df_final[df_final['Status'] == "💎 TOP PICK"]
                    st.subheader("📈 Ringkasan Performa (30 Hari Kalender)")
                    m1, m2, m3 = st.columns(3)
                    
                    if not top_df.empty:
                        wr = (len(top_df[top_df['Result'] == "Success"]) / len(top_df)) * 100
                        m1.metric("Top Picks", f"{len(top_df)}")
                        m2.metric("Win Rate", f"{wr:.1f}%")
                        m3.metric("Avg Vol Ratio", f"{top_df['Vol Ratio'].mean():.2f}x")
                    
                    st.divider()
                    tab1, tab2 = st.tabs(["Top Picks", "Watchlist"])
                    with tab1:
                        st.dataframe(top_df.sort_values('Vol Ratio', ascending=False), use_container_width=True, hide_index=True)
                    with tab2:
                        st.dataframe(df_final[df_final['Status'] == "Watchlist"].sort_values('Vol Ratio', ascending=False), use_container_width=True, hide_index=True)
                else:
                    st.warning("Data tidak ditemukan.")
            else:
                st.error("Tidak ada saham di rentang harga tersebut.")
else:
    st.error("File emiten tidak ditemukan.")
