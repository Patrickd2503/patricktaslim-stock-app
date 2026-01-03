import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

st.set_page_config(page_title="Monitor Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

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
    selected_tickers = st.sidebar.multiselect(
        "Pilih atau Ketik Kode Saham:",
        options=all_tickers,
        help="Jika diisi, filter harga di bawah akan diabaikan."
    )

    # 2. FILTER HARGA
    st.sidebar.subheader("Rentang Harga (IDR)")
    # Berikan catatan visual di UI
    if selected_tickers:
        st.sidebar.caption("⚠️ Filter harga sedang diabaikan (Mode Cari Kode)")
    
    min_price = st.sidebar.number_input("Harga Minimal", min_value=0, value=50)
    max_price = st.sidebar.number_input("Harga Maksimal", min_value=0, value=1500)
    
    st.sidebar.markdown("---")
    tipe = st.sidebar.radio("Tampilkan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=10))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Tarik Data"):
        with st.spinner('Sedang menarik data...'):
            # Menentukan list ticker yang akan didownload
            if selected_tickers:
                # KONDISI: Kode Saham Diinput (Range Harga di-ignore)
                df_to_fetch = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)]
                mode_pencarian = "kode"
            else:
                # KONDISI: Kode Saham Kosong (Gunakan daftar semua emiten untuk difilter harga nanti)
                df_to_fetch = df_emiten
                mode_pencarian = "harga"
            
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_fetch['Kode Saham'].dropna().unique()]
            
            if not tickers_jk:
                st.warning("Daftar saham kosong.")
            else:
                data = yf.download(tickers_jk, start=start_d, end=end_d, threads=True)['Close']
                
                if not data.empty:
                    if isinstance(data, pd.Series):
                        data = data.to_frame()
                    
                    df_work = data.ffill()
                    last_prices = df_work.iloc[-1]
                    
                    # LOGIKA FILTERING FINAL
                    if mode_pencarian == "kode":
                        # Ambil semua yang didownload tanpa filter harga
                        df_filtered = df_work 
                    else:
                        # Filter berdasarkan rentang harga
                        saham_lolos = last_prices[(last_prices >= min_price) & (last_prices <= max_price)].index
                        df_filtered = df_work[saham_lolos]

                    if not df_filtered.empty:
                        # Formatting Angka & Persen
                        if tipe == "Perubahan (%)":
                            df_raw = (df_filtered.pct_change() * 100)
                            df_final_data = df_raw.applymap(lambda x: f"{x:.1f}%".replace('.', ',') if pd.notnull(x) else "0,0%")
                        else:
                            df_final_data = df_filtered.applymap(lambda x: f"{int(x):,}" if pd.notnull(x) else "0")

                        # Format Tanggal di Index
                        df_final_data.index = df_final_data.index.strftime('%d/%m/%Y')
                        df_final_t = df_final_data.T
                        df_final_t.index = df_final_t.index.str.replace('.JK', '', regex=False)
                        
                        df_display = pd.merge(
                            df_emiten[['Kode Saham', 'Nama Perusahaan']], 
                            df_final_t, 
                            left_on='Kode Saham', 
                            right_index=True, 
                            how='inner'
                        )

                        cols_to_style = df_display.columns[2:]
                        styled_df = df_display.style.applymap(style_target, subset=cols_to_style)

                        st.success(f"Berhasil memuat {len(df_display)} saham.")
                        st.dataframe(styled_df, use_container_width=True)
                    else:
                        st.warning(f"Tidak ada saham yang ditemukan di rentang Rp{min_price} - Rp{max_price}")
                else:
                    st.error("Gagal menarik data dari Yahoo Finance.")
else:
    st.error("⚠️ File daftar saham tidak ditemukan di GitHub!")
