import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

st.set_page_config(page_title="Monitor Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# --- 1. FITUR CACHE (MEMPERCEPAT PENARIKAN DATA) ---
@st.cache_data(ttl=3600)  # Simpan data di memori selama 1 jam
def fetch_yf_data(tickers, start_date, end_date):
    return yf.download(tickers, start=start_date, end=end_date, threads=True)['Close']

# --- DAFTAR KEMUNGKINAN NAMA FILE ---
POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']

def load_data_auto():
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                if file_name.endswith('.csv'):
                    return pd.read_csv(file_name), file_name
                else:
                    return pd.read_excel(file_name), file_name
            except:
                continue
    return None, None

df_emiten, nama_file_aktif = load_data_auto()

# --- FUNGSI WARNA (STYLER) ---
def style_target(val):
    try:
        if isinstance(val, str):
            clean_val = val.replace('%', '').replace(',', '')
            num_val = float(clean_val)
        else:
            num_val = float(val)
            
        if num_val > 0:
            return 'background-color: rgba(144, 238, 144, 0.4)' 
        elif num_val < 0:
            return 'background-color: rgba(255, 182, 193, 0.4)' 
        elif num_val == 0:
            return 'background-color: rgba(255, 255, 0, 0.3)'   
    except:
        pass
    return ''

# --- LOGIKA TAMPILAN ---
if df_emiten is not None:
    st.sidebar.success(f"✅ Menggunakan: {nama_file_aktif}")
    st.sidebar.header("Filter & Konfigurasi")
    
    # 1. FILTER KODE SAHAM
    st.sidebar.subheader("Cari Kode Saham")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Pilih atau Ketik Kode Saham:", options=all_tickers)

    # 2. FILTER HARGA
    st.sidebar.subheader("Rentang Harga (IDR)")
    if selected_tickers:
        st.sidebar.caption("⚠️ Filter harga diabaikan (Mode Cari Kode)")
    min_price = st.sidebar.number_input("Harga Minimal", min_value=0, value=50)
    max_price = st.sidebar.number_input("Harga Maksimal", min_value=0, value=1500)
    
    st.sidebar.markdown("---")
    
    # 3. PILIHAN TAMPILAN (DENGAN SPLIT VIEW)
    tipe = st.sidebar.radio(
        "Tampilkan Data:", 
        ("Harga Penutupan (IDR)", "Perubahan (%)", "Split View (Keduanya)")
    )
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=10))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Tarik Data"):
        with st.spinner('Menarik data dari Yahoo Finance...'):
            if selected_tickers:
                df_to_fetch = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)]
                mode_pencarian = "kode"
            else:
                df_to_fetch = df_emiten
                mode_pencarian = "harga"
            
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_fetch['Kode Saham'].dropna().unique()]
            
            if not tickers_jk:
                st.warning("Daftar saham kosong.")
            else:
                # Menggunakan Fungsi Cache
                data = fetch_yf_data(tuple(tickers_jk), start_d, end_d)
                
                if not data.empty:
                    if isinstance(data, pd.Series): data = data.to_frame()
                    df_work = data.ffill()
                    last_prices = df_work.iloc[-1]
                    
                    if mode_pencarian == "kode":
                        df_filtered = df_work 
                    else:
                        saham_lolos = last_prices[(last_prices >= min_price) & (last_prices <= max_price)].index
                        df_filtered = df_work[saham_lolos]

                    if not df_filtered.empty:
                        # --- FUNGSI PROSES DATA ---
                        def format_pct(df):
                            res = (df.pct_change() * 100)
                            return res.applymap(lambda x: f"{x:.1f}%".replace('.', ',') if pd.notnull(x) else "0,0%")

                        def format_price(df):
                            return df.applymap(lambda x: f"{int(x):,}" if pd.notnull(x) else "0")

                        def prepare_display(df_data):
                            df_data.index = df_data.index.strftime('%d/%m/%Y')
                            df_t = df_data.T
                            df_t.index = df_t.index.str.replace('.JK', '', regex=False)
                            return pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_t, 
                                            left_on='Kode Saham', right_index=True, how='inner')

                        # --- LOGIKA SPLIT VIEW ATAU SINGLE VIEW ---
                        st.success(f"Berhasil memuat {len(df_filtered.columns)} saham.")

                        if tipe == "Perubahan (%)" or tipe == "Split View (Keduanya)":
                            st.subheader("📈 Perubahan Harga (%)")
                            df_pct = prepare_display(format_pct(df_filtered))
                            st.dataframe(df_pct.style.applymap(style_target, subset=df_pct.columns[2:]), use_container_width=True)

                        if tipe == "Harga Penutupan (IDR)" or tipe == "Split View (Keduanya)":
                            st.subheader("💰 Harga Penutupan (IDR)")
                            df_prc = prepare_display(format_price(df_filtered))
                            # Tetap gunakan style_target agar sel > 0 tetap berwarna hijau konsisten
                            st.dataframe(df_prc.style.applymap(style_target, subset=df_prc.columns[2:]), use_container_width=True)
                            
                    else:
                        st.warning(f"Tidak ada saham di rentang harga tersebut.")
                else:
                    st.error("Gagal menarik data.")
else:
    st.error("⚠️ File daftar saham tidak ditemukan di GitHub!")
