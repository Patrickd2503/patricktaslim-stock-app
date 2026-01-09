import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")

# Custom CSS untuk tampilan lebih profesional
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

st.title("🎯 Smart Money Monitor: Dashboard Akumulasi BEI")

# --- 1. LOAD DATA DARI GITHUB (FREE FLOAT) ---
@st.cache_data(ttl=3600) # Auto-refresh setiap 1 jam
def load_free_float_github():
    url = "https://github.com/Patrickd2503/patricktaslim-stock-app/raw/main/FreeFloat.xlsx"
    try:
        df_ff = pd.read_excel(url)
        # Bersihkan nama kolom dari spasi dan paksa ke uppercase untuk standarisasi
        df_ff.columns = df_ff.columns.str.strip()
        
        # Mapping kolom secara fleksibel (mengambil kolom 1 sebagai Ticker, kolom 2 sebagai Nilai FF)
        if len(df_ff.columns) >= 2:
            new_names = {df_ff.columns[0]: 'Ticker', df_ff.columns[1]: 'FF_Percent'}
            df_ff = df_ff.rename(columns=new_names)
        
        df_ff['Ticker'] = df_ff['Ticker'].astype(str).str.strip().str.upper()
        return df_ff
    except Exception as e:
        st.error(f"⚠️ Gagal sinkronisasi dengan GitHub: {e}")
        return pd.DataFrame()

# --- 2. FETCH DATA MARKET (YFINANCE) ---
@st.cache_data(ttl=1800) # Refresh data market setiap 30 menit
def fetch_yf_data(tickers, start_date, end_date):
    # Tambah buffer waktu untuk perhitungan MA20
    extended_start = start_date - timedelta(days=60)
    try:
        df = yf.download(list(tickers), start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        # Handling jika user hanya pilih 1 saham (Yfinance return single index)
        if len(tickers) == 1:
            c_df = df[['Close']].rename(columns={'Close': tickers[0]})
            v_df = df[['Volume']].rename(columns={'Volume': tickers[0]})
            return c_df, v_df
            
        return df['Close'], df['Volume']
    except Exception as e:
        st.error(f"❌ Error Yahoo Finance: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- 3. LOAD DATABASE LOKAL (KODE SAHAM) ---
def load_local_codes():
    for file in ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'Kode Saham.csv']:
        if os.path.exists(file):
            try:
                df = pd.read_csv(file) if file.endswith('.csv') else pd.read_excel(file)
                df.columns = df.columns.str.strip()
                return df
            except: continue
    return None

# --- 4. LOGIKA ANALISA ---
def run_smart_money_analysis(df_c, df_v, df_ff_ref):
    results = []
    shortlist = []
    
    for ticker_jk in df_c.columns:
        ticker_clean = str(ticker_jk).replace('.JK', '').upper()
        
        # Ambil data dan bersihkan NaN
        prices = df_c[ticker_jk].dropna()
        volumes = df_v[ticker_jk].dropna()
        
        if len(prices) < 20: continue
        
        # Perhitungan Indikator
        last_price = prices.iloc[-1]
        v_sma5 = volumes.rolling(5).mean().iloc[-1]
        v_sma20 = volumes.rolling(20).mean().iloc[-1]
        v_last = volumes.iloc[-1]
        
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        v_ma_ratio = v_sma5 / v_sma20 if v_sma20 > 0 else 0
        vol_control = (v_ratio / (v_ratio + 1)) * 100
        
        # Performa 5 Hari (Sideways detection)
        chg_5d = (prices.iloc[-1] - prices.iloc[-5]) / prices.iloc[-5] if len(prices) >= 5 else 0
        
        # Ambil Data Free Float dari Master GitHub
        ff_val = "N/A"
        if not df_ff_ref.empty and 'Ticker' in df_ff_ref.columns:
            match = df_ff_ref[df_ff_ref['Ticker'] == ticker_clean]
            if not match.empty:
                ff_val = match['FF_Percent'].values[0]

        # Logika Sinyal
        is_sideways = abs(chg_5d) < 0.03
        is_liquid = (v_last * last_price) > 500_000_000 # Transaksi > 500jt
        
        status = "Normal"
        if is_sideways and v_ratio >= 1.2:
            status = f"💎 Akumulasi (V:{v_ratio:.1f})"
            if vol_control > 65 and is_liquid:
                shortlist.append(ticker_clean)
        elif chg_5d > 0.05:
            status = "🚀 Markup"
        elif chg_5d < -0.05:
            status = "📉 Distribution"

        results.append({
            'Ticker': ticker_clean,
            'Sinyal': status,
            'Harga': int(last_price),
            'Chg 5D (%)': f"{chg_5d*100:.1f}%",
            'Vol Control': f"{vol_control:.1f}%",
            'Vol Ratio (MA5/20)': round(v_ma_ratio, 2),
            'Free Float': f"{ff_val:.1f}%" if isinstance(ff_val, (int, float)) else ff_val,
            'Volume (Lot)': f"{int(v_last/100):,}"
        })
        
    return pd.DataFrame(results), shortlist

# --- 5. INTERFACE DASHBOARD ---
df_master_emiten = load_local_codes()
df_ff_github = load_free_float_github()

if df_master_emiten is not None:
    # Sidebar
    st.sidebar.header("⚙️ Konfigurasi")
    
    # Filter Ticker
    list_saham = sorted(df_master_emiten.iloc[:, 0].dropna().unique().tolist())
    selected = st.sidebar.multiselect("Pilih Saham (Kosongkan untuk Semua):", options=list_saham)
    
    # Filter Harga
    min_p, max_p = st.sidebar.slider("Rentang Harga (IDR):", 50, 20000, (50, 5000))
    
    # Range Waktu
    col1, col2 = st.sidebar.columns(2)
    start_date = col1.date_input("Mulai", date.today() - timedelta(days=20))
    end_date = col2.date_input("Akhir", date.today())
    
    if st.sidebar.button("🔍 Jalankan Analisa Sekarang"):
        # 1. Tentukan list ticker yang akan diproses
        final_list = selected if selected else list_saham
        tickers_jk = [str(s).strip() + ".JK" for s in final_list]
        
        with st.spinner(f'Menganalisa {len(tickers_jk)} saham dari market...'):
            # 2. Ambil data market
            df_c, df_v = fetch_yf_data(tickers_jk, start_date, end_date)
            
            if not df_c.empty:
                # 3. Filter berdasarkan harga terakhir
                last_p_series = df_c.ffill().iloc[-1]
                saham_lolos = last_p_series[(last_p_series >= min_p) & (last_p_series <= max_p)].index
                
                if not saham_lolos.empty:
                    # 4. Jalankan Analisa Akumulasi
                    df_final, top_picks = run_smart_money_analysis(df_c[saham_lolos], df_v[saham_lolos], df_ff_github)
                    
                    # 5. Tampilkan Hasil
                    if top_picks:
                        st.success(f"🔥 **Saham Potensial (High Control + Liquid):** {', '.join(top_picks)}")
                    
                    # Tampilkan Tabel dengan Highlight
                    def highlight_signal(s):
                        if 'Akumulasi' in str(s): return 'background-color: #d4edda; color: #155724'
                        if 'Markup' in str(s): return 'background-color: #fff3cd; color: #856404'
                        return ''

                    st.subheader("📋 Tabel Hasil Pemindaian")
                    st.dataframe(
                        df_final.style.applymap(highlight_signal, subset=['Sinyal']),
                        use_container_width=True,
                        height=500
                    )
                    
                    # Fitur Download
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        df_final.to_excel(writer, index=False)
                    st.download_button(
                        label="📥 Download Excel Report",
                        data=output.getvalue(),
                        file_name=f"SmartMoney_{date.today()}.xlsx",
                        mime="application/vnd.ms-excel"
                    )
                else:
                    st.warning("Tidak ada saham yang memenuhi kriteria rentang harga.")
            else:
                st.error("Gagal mengambil data dari Yahoo Finance. Coba kurangi jumlah saham atau periksa koneksi.")
else:
    st.error("File 'Kode Saham.xlsx' tidak ditemukan di direktori utama.")
