import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham Ultra v5: Real Broxum", layout="wide")
st.title("🎯 Smart Money + Broker Summary (Real-Time EOD)")

# --- 1. INTEGRASI LIBRARY BROKER SUMMARY (NOMOR 1) ---
def get_broker_data_real(ticker, analysis_date):
    """
    Fungsi placeholder untuk menghubungkan ke library/API Broker Summary.
    """
    try:
        # Hubungkan ke library Broxum pilihan Anda di sini
        # Contoh return sementara (Simulasi)
        return "AK", "Accum" 
    except:
        return "-", "No Data"

# --- 2. CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    # Buffer 100 hari untuk kalkulasi MA yang akurat
    extended_start = start_date - timedelta(days=100)
    df = yf.download(tickers, start=extended_start, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

@st.cache_data(ttl=86400)
def get_free_float(ticker_jk):
    try:
        info = yf.Ticker(ticker_jk).info
        f_shares = info.get('floatShares')
        total_s = info.get('sharesOutstanding')
        if f_shares and total_s: return (f_shares / total_s) * 100
    except: pass
    return None

# --- 3. FUNGSI LOAD DATA ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

# --- 4. STYLE TOOLKIT ---
def style_percentage(val):
    try:
        num = float(str(val).replace('%', ''))
        if num > 0: return 'background-color: rgba(144, 238, 144, 0.4)'
        elif num < 0: return 'background-color: rgba(255, 182, 193, 0.4)'
        return 'background-color: rgba(255, 255, 0, 0.2)'
    except: return ''

def style_control(val):
    try:
        num = float(str(val).replace('%', ''))
        if num > 70: return 'background-color: #ff4b4b; color: white'
        if num > 50: return 'background-color: #ffa500; color: black'
    except: pass
    return ''

# --- 5. LOGIKA ANALISA v5 (REFINED) ---
def get_signals_and_data(df_c, df_v, analysis_date, is_analisa_lengkap=False):
    results, shortlist_keys = [], []
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 50: continue

        # Kalkulasi Indikator (MA tetap dihitung secara internal)
        ma20 = c.rolling(20).mean().iloc[-1]
        ma50 = c.rolling(50).mean().iloc[-1]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_last = v.iloc[-1]
        v_ratio = v_last / v_sma5 if v_sma5 > 0 else 0
        chg_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        price = c.iloc[-1]
        ticker = col.replace('.JK', '')
        vol_control_pct = (v_ratio / (v_ratio + 1)) * 100
        
        status_sm, status_bx, top_buyer = "Normal", "-", "-"
        
        if is_analisa_lengkap:
            # Tarik data Broker
            top_buyer, status_bx = get_broker_data_real(ticker, analysis_date)
            
            # Kriteria Longgar (Double Confirmation)
            is_sideways = abs(chg_5d) < 0.04 
            is_near_ma20 = price <= 1.05 * ma20
            
            if is_sideways and v_ratio >= 1.05:
                status_sm = f"💎 Akum (V:{v_ratio:.1f})"
                if vol_control_pct > 55 and status_bx in ['Accum', 'Big Accum'] and is_near_ma20:
                    shortlist_keys.append(ticker)
            elif chg_5d > 0.05: status_sm = "🚀 Markup"

        results.append({
            'Kode Saham': ticker,
            'Smart Money': status_sm,
            'Broxum': status_bx,
            'Top Buyer': top_buyer,
            'Vol Control (%)': f"{vol_control_pct:.1f}%",
            'Harga': int(price),
            'Total Lot': f"{int(v_last/100):,}",
            'Rata Lot': f"{int(v_sma5/100):,}"
        })
    return pd.DataFrame(results), shortlist_keys

# --- 6. RENDER DASHBOARD ---
df_emiten, _ = load_data_auto()

if df_emiten is not None:
    # --- SIDEBAR LENGKAP ---
    st.sidebar.header("Filter & Parameter")
    
    # Pencarian Kode
    selected_tickers = st.sidebar.multiselect(
        "Cari Kode:", 
        options=sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    )
    
    # Filter Range Harga
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=5000)
    
    # Range Tanggal
    start_d = st.sidebar.date_input("Mulai", date(2025, 12, 1))
    end_d = st.sidebar.date_input("Akhir", date(2026, 1, 5))

    st.sidebar.markdown("---")
    
    # Tombol Kontrol
    btn_split = st.sidebar.button("📊 1. Split View (Data Histori)")
    btn_analisa = st.sidebar.button("🚀 2. Jalankan Analisa Smart Broxum")

    if btn_split or btn_analisa:
        with st.spinner('Memproses data...'):
            # Filter Emiten
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].dropna().unique()]
            
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

            if not df_c_raw.empty:
                df_c = df_c_raw.ffill()
                last_p = df_c.iloc[-1]
                
                # Filter berdasarkan range harga di sidebar
                saham_lolos = df_c.columns if selected_tickers else last_p[(last_p >= min_p) & (last_p <= max_p)].index
                df_f_c, df_f_v = df_c[saham_lolos], df_v_raw[saham_lolos]
                
                # Jalankan Analisa
                df_analysis, shortlist_keys = get_signals_and_data(df_f_c, df_f_v, end_d, is_analisa_lengkap=btn_analisa)
                
                # Menyiapkan Tampilan Harian (Transpose)
                df_view = df_f_c.loc[pd.to_datetime(start_d):]
                df_pct = (df_view.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")
                df_pct.index = df_pct.index.strftime('%d/%m/%Y')
                df_harian = df_pct.T
                df_harian.index = df_harian.index.str.replace('.JK', '')
                
                # Merge Data Analisa dengan Nama Perusahaan & Histori Harian
                df_merged = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_analysis, on='Kode Saham')
                df_final = pd.merge(df_merged, df_harian, left_on='Kode Saham', right_index=True)

                # RENDER TABEL SHORTLIST
                if btn_analisa:
                    st.subheader("🎯 Shortlist Terpilih (SM + Broxum)")
                    df_top = df_final[df_final['Kode Saham'].isin(shortlist_keys)]
                    if not df_top.empty:
                        st.dataframe(df_top.style.applymap(style_control, subset=['Vol Control (%)'])
                                              .applymap(style_percentage, subset=df_top.columns[10:]), use_container_width=True)
                    else:
                        st.warning("Tidak ada saham yang masuk kriteria shortlist saat ini.")

                # RENDER SEMUA DATA
                st.subheader("📊 Semua Data Pantauan")
                st.dataframe(df_final.style.applymap(style_control, subset=['Vol Control (%)'])
                                          .applymap(style_percentage, subset=df_final.columns[10:]), use_container_width=True)
            else:
                st.error("Koneksi gagal atau data tidak ditemukan.")
else:
    st.error("File 'Kode Saham.xlsx' belum ditemukan. Silakan pastikan file ada di repositori.")
