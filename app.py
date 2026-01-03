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
            # Bersihkan format ribuan dan persen untuk pengecekan angka
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
    
    # 1. FILTER KODE SAHAM (SEARCH BOX)
    st.sidebar.subheader("Cari Kode Saham")
    all_tickers = df_emiten['Kode Saham'].dropna().unique().tolist()
    selected_tickers = st.sidebar.multiselect(
        "Pilih atau Ketik Kode Saham:",
        options=all_tickers,
        help="Kosongkan jika ingin menampilkan semua saham berdasarkan filter harga"
    )

    # 2. FILTER HARGA
    st.sidebar.subheader("Rentang Harga (IDR)")
    min_price = st.sidebar.number_input("Harga Minimal", min_value=0, value=50, step=1)
    max_price = st.sidebar.number_input("Harga Maksimal", min_value=0, value=1500, step=1)
    
    st.sidebar.markdown("---")
    tipe = st.sidebar.radio("Tampilkan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=10))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Tarik Data"):
        with st.spinner('Sedang menarik data...'):
            # Logika filter emiten sebelum download
            df_to_fetch = df_emiten.copy()
            if selected_tickers:
                df_to_fetch = df_to_fetch[df_to_fetch['Kode Saham'].isin(selected_tickers)]
            
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_fetch['Kode Saham'].dropna().unique()]
            
            if not tickers_jk:
                st.warning("Tidak ada kode saham yang terpilih.")
            else:
                data = yf.download(tickers_jk, start=start_d, end=end_d, threads=True)['Close']
                
                if not data.empty:
                    # Jika hanya 1 saham, yfinance mengembalikan Series, kita ubah ke DataFrame
                    if isinstance(data, pd.Series):
                        data = data.to_frame()
                    
                    df_work = data.ffill()
                    last_prices = df_work.iloc[-1]
                    
                    # Tetap jalankan filter harga jika user tidak memilih kode saham spesifik
                    # Jika user pilih kode saham, filter harga tetap berlaku sebagai filter tambahan
                    saham_lolos = last_prices[(last_prices >= min_price) & (last_prices <= max_price)].index
                    df_filtered = df_work[saham_lolos]

                    if not df_filtered.empty:
                        if tipe == "Perubahan (%)":
                            df_processed = (df_filtered.pct_change() * 100)
                            df_final_data = df_processed.applymap(lambda x: f"{x:.1f}%".replace('.', ',') if pd.notnull(x) else "0,0%")
                        else:
                            df_final_data = df_filtered.applymap(lambda x: f"{int(x):,}" if pd.notnull(x) else "0")

                        # Format Tanggal
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

                        st.success(f"Ditemukan {len(df_display)} saham.")
                        st.dataframe(styled_df, use_container_width=True)
                    else:
                        st.warning(f"Tidak ada saham di range harga Rp{min_price} - Rp{max_price}")
                else:
                    st.error("Data tidak ditemukan di Yahoo Finance.")
else:
    st.error("⚠️ File daftar saham tidak ditemukan di GitHub!")
