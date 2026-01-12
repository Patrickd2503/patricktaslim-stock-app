import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v11", layout="wide")
st.title("🎯 Dashboard Akumulasi: Smart Money Monitor")

# --- 1. FITUR CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    # Menambah buffer 450 hari untuk perhitungan MA dan MFI yang akurat
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        # Penanganan MultiIndex jika mendownload banyak ticker
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low']
        else:
            # Jika hanya 1 ticker, yfinance mengembalikan format yang berbeda
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']]
            
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATABASE EMITEN ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx', 'Kode_Saham.xlsx', 'data.csv']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try: 
                df = pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)
                if 'Kode Saham' in df.columns:
                    return df, file_name
            except: continue
    
    # List default jika file tidak ditemukan
    default_data = pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN', 'STRK', 'KAEF', 'ICON', 'SPRE', 'LIVE', 'VIVA', 'BUMI', 'GOTO', 'BBCA', 'BMRI', 'TLKM']})
    return default_data, "Default Mode (File Not Found)"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI STYLING & EXCEL ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white' # Overbought
        if num <= 40: return 'background-color: #008000; color: white' # Potential Accumulation
    except: pass
    return ''

def highlight_outperform(row):
    return ['background-color: #1e3d59; color: white' if row['Market RS'] == 'Outperform' else '' for _ in row]

def style_percentage(val):
    try:
        if val > 0: return 'color: green'
        elif val < 0: return 'color: red'
    except: pass
    return ''

def to_excel_multi_sheet(df_shortlist, df_all, df_pct, df_prc):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_shortlist.to_excel(writer, index=False, sheet_name='1. Shortlist')
        df_all.to_excel(writer, index=False, sheet_name='2. Analisa Utama')
        df_pct.tail(100).to_excel(writer, index=True, sheet_name='3. Histori Persen')
        df_prc.tail(100).to_excel(writer, index=True, sheet_name='4. Histori Harga')
    return output.getvalue()

# --- 4. LOGIKA ANALISA TEKNIKAL ---
def get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=False, min_avg_volume=1000000):
    results, shortlist_keys = [], []
    
    # Hitung performa IHSG sebagai benchmark (20 hari terakhir)
    if "^JKSE" in df_c.columns:
        ihsg_c = df_c["^JKSE"].dropna()
        ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0
    else:
        ihsg_perf = 0

    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col): continue
        
        # Bersihkan data dari NaN
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        h = df_h[col].dropna()
        l = df_l[col].dropna()
        
        if len(c) < 30: continue
        
        # Filter minimum volume rata-rata 20 hari
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        if avg_vol20 < min_avg_volume: 
            continue

        # Hitung MFI (Money Flow Index)
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf)))
        last_mfi = mfi_series.iloc[-1] if not np.isnan(mfi_series.iloc[-1]) else 50
        
        # Indikator Tren & Volume
        ma20 = c.rolling(20).mean().iloc[-1]
        v_sma20 = v.rolling(20).mean().iloc[-1]
        last_p = c.iloc[-1]
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        trend = "Diatas MA20" if last_p > ma20 else "Dibawah MA20"
        
        # Price Volume Analysis (PVA)
        pva = "Neutral"
        if p_change > 1 and v.iloc[-1] > v_sma20: pva = "Bullish Vol"
        elif p_change < -1 and v.iloc[-1] > v_sma20: pva = "Bearish Vol"
        elif abs(p_change) < 1 and v.iloc[-1] > v_sma20: pva = "Churning"

        # Market Relative Strength (RS)
        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        # Kriteria Shortlist: Bullish Vol + Low MFI + Uptrend
        ticker_name = str(col).replace('.JK','')
        if is_analisa_lengkap and pva == "Bullish Vol" and last_mfi < 60 and last_p > ma20:
            shortlist_keys.append(ticker_name)

        results.append({
            'Kode Saham': ticker_name,
            'Tren (MA20)': trend,
            'MFI (14D)': round(last_mfi, 2),
            'PVA': pva,
            'Market RS': rs,
            'Last Price': int(last_p),
            'Vol/SMA20': round(v.iloc[-1] / v_sma20, 2) if v_sma20 > 0 else 0,
            'AvgVol20': int(avg_vol20)
        })
        
    return pd.DataFrame(results), shortlist_keys

# --- 5. RENDER SIDEBAR & PARAMETER ---
st.sidebar.info(f"📁 Database: {loaded_file}")

if not df_emiten.empty:
    st.sidebar.header("⚙️ Parameter Analisa")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Pilih Kode Spesifik (Kosongkan untuk Semua):", options=all_tickers)
    
    min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
    max_p = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
    min_vol = st.sidebar.number_input("Minimal Avg Vol (20 hari)", value=1000000, step=100000)
    
    # Rentang Tanggal
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    st.sidebar.markdown("---")
    show_histori = st.sidebar.checkbox("📊 Tampilkan Tabel Histori")
    btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

    # --- 6. EKSEKUSI ANALISA ---
    if btn_analisa:
        with st.spinner('Sedang menarik data dari Yahoo Finance...'):
            target_list = selected_tickers if selected_tickers else all_tickers
            tickers_jk = [str(k).strip() + ".JK" for k in target_list]
            
            df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c.empty:
                # Perbaikan Nama Kolom MultiIndex
                if isinstance(df_c.columns, pd.MultiIndex):
                    df_c.columns = df_c.columns.get_level_values(1)
                    df_v.columns = df_v.columns.get_level_values(1)
                    df_h.columns = df_h.columns.get_level_values(1)
                    df_l.columns = df_l.columns.get_level_values(1)

                df_analysis, shortlist_keys = get_signals_and_data(df_c, df_v, df_h, df_l, is_analisa_lengkap=True, min_avg_volume=min_vol)
                
                # Filter berdasarkan range harga
                if not df_analysis.empty:
                    df_analysis = df_analysis[(df_analysis['Last Price'] >= min_p) & (df_analysis['Last Price'] <= max_p)]
                
                if not df_analysis.empty:
                    # Dashboard Metrics
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Saham Terfilter", len(df_analysis))
                    m2.metric("Sinyal Smart Money", len(shortlist_keys))
                    m3.metric("IHSG Benchmark", "Active")

                    # Tampilan Tab
                    tab1, tab2 = st.tabs(["🔍 Tabel Analisa Utama", "📈 Data Histori"])

                    with tab1:
                        st.subheader("Hasil Screening Teknikal")
                        styled_df = df_analysis.style\
                            .applymap(style_mfi, subset=['MFI (14D)'])\
                            .apply(highlight_outperform, axis=1)
                        
                        st.dataframe(styled_df, use_container_width=True, height=500)
                        
                        if shortlist_keys:
                            st.success(f"🔥 **SAHAM SHORTLIST (Potensi Akumulasi):** {', '.join(shortlist_keys)}")
                        else:
                            st.info("Tidak ada saham yang masuk kriteria shortlist saat ini.")

                    with tab2:
                        if show_histori:
                            st.subheader("Perubahan Harga Harian (%)")
                            st.dataframe((df_c.pct_change() * 100).tail(10).style.applymap(style_percentage))
                            st.subheader("Volume Transaksi Harian")
                            st.dataframe(df_v.tail(10))
                        else:
                            st.warning("Centang 'Tampilkan Tabel Histori' di sidebar untuk melihat bagian ini.")

                    # Tombol Download
                    report_excel = to_excel_multi_sheet(
                        df_analysis[df_analysis['Kode Saham'].isin(shortlist_keys)],
                        df_analysis,
                        df_c.pct_change()*100,
                        df_c
                    )
                    st.sidebar.download_button(
                        label="📥 Download Report Excel",
                        data=report_excel,
                        file_name=f"Analisa_BEI_{today}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("Tidak ada data yang cocok dengan filter harga/volume Anda.")
            else:
                st.error("Gagal mengambil data. Pastikan koneksi internet stabil dan kode saham benar.")

else:
    st.error("Database saham kosong. Silakan periksa file input Anda.")

st.markdown("---")
st.caption("Note: MFI < 40 mengindikasikan area oversold/akumulasi. PVA 'Bullish Vol' menunjukkan kenaikan harga dengan dukungan volume.")
