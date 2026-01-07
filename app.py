import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Top Pick Momentum Monitor", layout="wide")
st.title("💎 Top Pick Momentum Screener")

# --- 1. FUNGSI FETCH HARGA TERAKHIR (UNTUK FILTER AWAL) ---
def get_current_prices(tickers):
    try:
        data = yf.download(tickers, period="1d", threads=True, progress=False)
        if data.empty: return pd.Series()
        # Mengambil harga Close terakhir
        if isinstance(data.columns, pd.MultiIndex):
            return data['Close'].iloc[-1]
        return data['Close']
    except:
        return pd.Series()

# --- 2. FUNGSI FETCH DATA HISTORI (UNTUK ANALISA) ---
@st.cache_data(ttl=3600)
def fetch_hist_data(tickers, start_date, end_date):
    # Buffer data 1 tahun untuk akurasi indikator MACD & RSI
    extended_start = start_date - timedelta(days=365)
    try:
        df = yf.download(list(tickers), start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty: return pd.DataFrame(), pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume']
        return df[['Close']], df[['Volume']]
    except:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. LOGIKA ANALISA HIGH CONVICTION ---
def get_signals(df_c, df_v):
    results, shortlist_keys = [], []
    if df_c.empty: return pd.DataFrame(), []

    for col in df_c.columns:
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        if len(c) < 35: continue 
        
        # Indikator
        rsi = ta.rsi(c, length=14)
        rsi_val = float(rsi.iloc[-1]) if rsi is not None and not rsi.empty else 50
        
        macd = ta.macd(c)
        # Ambil histogram terakhir secara aman (float tunggal)
        macd_h = float(macd.filter(like='MACDh').iloc[-1]) if macd is not None and not macd.empty else 0
        
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        price_last = float(c.iloc[-1])
        
        v_ratio = float(v_last / v_sma20) if v_sma20 > 0 else 0
        turnover = v_last * price_last
        
        # KRITERIA KETAT
        is_strong_rsi = 55 < rsi_val < 70
        is_bullish_macd = macd_h > 0
        is_above_ma20 = price_last > ma20
        is_ultra_vol = v_ratio > 2.5
        is_liquid = turnover > 2_000_000_000 # Min Transaksi 2 Miliar
        
        ticker = str(col).replace('.JK','')
        
        if is_strong_rsi and is_bullish_macd and is_above_ma20 and is_ultra_vol and is_liquid:
            status = "💎 TOP PICK"
            shortlist_keys.append(ticker)
        elif is_bullish_macd and is_above_ma20 and v_ratio > 1.2:
            status = "⚡ Momentum"
        else:
            status = "Wait & See"

        results.append({
            'Kode Saham': ticker,
            'Status': status,
            'Last Price': int(price_last),
            'Vol Ratio': round(v_ratio, 2),
            'RSI (14)': round(rsi_val, 2),
            'Turnover (M)': round(turnover / 1_000_000_000, 2),
            'MA20 Dist (%)': round(((price_last - ma20) / ma20) * 100, 2)
        })
        
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res = df_res.sort_values(by='Vol Ratio', ascending=False)
    return df_res, shortlist_keys

# --- 4. MAIN APP ---
def load_emiten():
    for f in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(f):
            try:
                df = pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)
                df.columns = [c.strip() for c in df.columns]
                return df
            except: continue
    return None

df_emiten = load_emiten()

if df_emiten is not None:
    st.sidebar.header("Filter Parameter")
    all_codes = sorted(df_emiten['Kode Saham'].unique().tolist())
    selected = st.sidebar.multiselect("Pantau Kode Spesifik:", options=all_codes)
    
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=900)
    
    # --- INPUT PERIODE (DIMUNCULKAN KEMBALI) ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("Periode Analisa")
    start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=30))
    end_d = st.sidebar.date_input("Akhir", date.today())

    if st.sidebar.button("🚀 Jalankan Analisa"):
        target_codes = selected if selected else df_emiten['Kode Saham'].tolist()
        tickers_jk = [str(t).strip() + ".JK" for t in target_codes]
        
        with st.spinner('Menyaring harga...'):
            current_prices = get_current_prices(tickers_jk)
            # Saring saham yang harganya masuk rentang
            saham_lolos = current_prices[(current_prices >= min_p) & (current_prices <= max_p)].index.tolist()
            
        if saham_lolos:
            st.info(f"Ditemukan {len(saham_lolos)} saham dalam rentang harga. Memulai analisa momentum...")
            with st.spinner('Menarik data histori & menghitung indikator...'):
                c_raw, v_raw = fetch_hist_data(saham_lolos, start_d, end_d)
                
                if not c_raw.empty:
                    # Penanganan jika hanya 1 saham yang lolos
                    if len(saham_lolos) == 1:
                        c_raw.columns = [saham_lolos[0]]
                        v_raw.columns = [saham_lolos[0]]

                    df_res, shortlists = get_signals(c_raw, v_raw)
                    
                    st.subheader("🎯 Top Pick Terpilih")
                    df_top = df_res[df_res['Status'] == "💎 TOP PICK"]
                    if not df_top.empty:
                        st.dataframe(df_top, use_container_width=True)
                    else:
                        st.info("Tidak ada saham yang memenuhi kriteria ultra ketat 'TOP PICK' saat ini.")
                        
                    st.divider()
                    st.subheader("📊 Hasil Screening Lengkap (Auto-Sort by Vol Ratio)")
                    st.dataframe(df_res, use_container_width=True)
                else:
                    st.error("Gagal mengambil data histori. Pastikan periode tanggal valid.")
        else:
            st.warning("Tidak ada saham yang ditemukan dalam rentang harga tersebut.")
else:
    st.error("File database 'Kode Saham.xlsx' tidak ditemukan.")
