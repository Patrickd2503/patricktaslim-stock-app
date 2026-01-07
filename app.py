import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import date, timedelta
import os

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Top Pick Momentum Monitor", layout="wide")

st.title("💎 Top Pick Momentum Screener")
st.markdown("### Strategi High Conviction: RSI, MACD, MA20 & Turnover Filter")

# --- 1. FUNGSI FETCH DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_data(tickers, start_date, end_date):
    extended_start = start_date - timedelta(days=365)
    try:
        ticker_list = list(tickers) if isinstance(tickers, (list, tuple, set)) else [tickers]
        df = yf.download(ticker_list, start=extended_start, end=end_date, threads=True, progress=False)
        
        if df.empty: return pd.DataFrame(), pd.DataFrame()
        
        if len(ticker_list) == 1:
            close_df = df[['Close']].rename(columns={'Close': ticker_list[0]})
            volume_df = df[['Volume']].rename(columns={'Volume': ticker_list[0]})
        else:
            close_df = df['Close']
            volume_df = df['Volume']
            
        return close_df, volume_df
    except:
        return pd.DataFrame(), pd.DataFrame()

# --- 2. LOGIKA ANALISA HIGH CONVICTION ---
def get_signals(df_c, df_v):
    results, shortlist_keys = [], []
    if df_c.empty: return pd.DataFrame(), []

    for col in df_c.columns:
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        
        if len(c) < 35: continue 
        
        # Indikator Teknikal
        rsi = ta.rsi(c, length=14)
        rsi_last = rsi.iloc[-1] if rsi is not None else 50
        
        macd = ta.macd(c)
        macd_h = macd.filter(like='MACDh').iloc[-1] if macd is not None and not macd.empty else 0
        
        # Logika Trend & Volume
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        v_last = v.iloc[-1]
        price_last = c.iloc[-1]
        
        v_ratio = v_last / v_sma20 if v_sma20 > 0 else 0
        turnover = v_last * price_last # Estimasi nilai transaksi (asumsi v adalah lembar)
        
        # --- PARAMETER PENGETATAN ---
        is_strong_rsi = 55 < rsi_last < 70       # RSI zona ledakan momentum
        is_bullish_macd = macd_h > 0            # Histogram MACD positif
        is_above_ma20 = price_last > ma20       # Menjamin sedang Uptrend
        is_ultra_vol = v_ratio > 2.5            # Ledakan volume > 2.5x rata-rata
        is_liquid = turnover > 2_000_000_000    # Minimal Transaksi Rp 2 Miliar
        
        ticker = str(col).replace('.JK','')
        
        # Penentuan Status
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
            'RSI (14)': round(rsi_last, 2),
            'Turnover (M)': round(turnover / 1_000_000_000, 2),
            'MA20 Dist (%)': round(((price_last - ma20) / ma20) * 100, 2)
        })
        
    df_results = pd.DataFrame(results)
    
    # --- AUTO SORT ---
    # Mengurutkan berdasarkan Volume Ratio tertinggi (indikasi kuat partisipasi bandar)
    if not df_results.empty:
        df_results = df_results.sort_values(by='Vol Ratio', ascending=False)
        
    return df_results, shortlist_keys

# --- 3. LOAD DATABASE ---
def load_emiten():
    for f in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(f):
            try:
                df = pd.read_csv(f) if f.endswith('.csv') else pd.read_excel(f)
                df.columns = [c.strip() for c in df.columns]
                return df
            except: continue
    return None

# --- 4. MAIN APP ---
df_emiten = load_emiten()

if df_emiten is not None:
    st.sidebar.header("Filter Parameter")
    all_codes = sorted(df_emiten['Kode Saham'].unique().tolist())
    selected_codes = st.sidebar.multiselect("Pantau Kode Spesifik:", options=all_codes)
    
    min_p = st.sidebar.number_input("Harga Min", value=100) # Dinaikkan ke 100 untuk hindari penny stocks
    max_p = st.sidebar.number_input("Harga Max", value=10000)
    
    start_d = st.sidebar.date_input("Mulai", date.today() - timedelta(days=30))
    end_d = st.sidebar.date_input("Akhir", date.today())

    if st.sidebar.button("🚀 Jalankan Analisa High Conviction"):
        target_codes = selected_codes if selected_codes else df_emiten['Kode Saham'].tolist()
        tickers = [str(t).strip() + ".JK" for t in target_codes]
        
        with st.spinner(f'Menganalisa {len(tickers)} saham dengan kriteria ketat...'):
            c_raw, v_raw = fetch_yf_data(tickers, start_d, end_d)
        
        if not c_raw.empty:
            last_p = c_raw.ffill().iloc[-1]
            saham_lolos = last_p[(last_p >= min_p) & (last_p <= max_p)].index
            
            if len(saham_lolos) > 0:
                df_res, shortlists = get_signals(c_raw[saham_lolos], v_raw[saham_lolos])
                
                # Filter Shortlist Tabel Atas
                df_top = df_res[df_res['Status'] == "💎 TOP PICK"]
                
                st.subheader("🎯 Top Pick Terpilih (Konfirmasi Kuat)")
                if not df_top.empty:
                    st.success(f"Berhasil menyaring menjadi {len(df_top)} Saham Terbaik.")
                    st.dataframe(df_top, use_container_width=True)
                else:
                    st.info("Tidak ada saham yang memenuhi kriteria ultra ketat hari ini.")
                
                st.divider()
                st.subheader("📊 Semua Hasil (Auto-Sorted by Vol Ratio)")
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning("Tidak ada saham dalam rentang harga tersebut.")
        else:
            st.error("Gagal menarik data. Cek koneksi atau kode saham di file Excel.")
else:
    st.error("File 'Kode Saham.xlsx' tidak ditemukan.")
