import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

# Konfigurasi halaman
st.set_page_config(page_title="Monitor Saham BEI", layout="wide")

# --- NAMA FILE SESUAI GITHUB ANDA ---
FILE_NAME = 'Kode Saham.xlsx - Sheet1.csv'

# Judul Utama
st.title("📊 Monitoring Saham BEI")

# Fungsi untuk memuat file secara otomatis
def get_data():
    if os.path.exists(FILE_NAME):
        # Jika file ditemukan di GitHub, baca langsung
        return pd.read_csv(FILE_NAME)
    else:
        return None

df_emiten = get_data()

# --- LOGIKA TAMPILAN ---
if df_emiten is not None:
    # JIKA FILE DITEMUKAN: Tampilkan menu utama (Tanpa Upload)
    st.sidebar.success(f"✅ Data Terdeteksi: {len(df_emiten)} Emiten")
    
    st.sidebar.header("Filter & Konfigurasi")
    min_p, max_p = st.sidebar.slider("Rentang Harga (IDR)", 50, 15000, (50, 1500))
    tipe = st.sidebar.radio("Tampilkan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=7))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Ambil Data Terbaru"):
        with st.spinner('Menarik data dari Yahoo Finance...'):
            tickers = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
            
            try:
                # Mengambil data Close
                data = yf.download(tickers, start=start_d, end=end_d, threads=True)['Close']
                
                if not data.empty:
                    # Ambil harga terakhir yang tersedia (handle weekend/libur)
                    last_valid_row = data.ffill().iloc[-1]
                    
                    # Filter berdasarkan range harga slider
                    saham_lolos = last_valid_row[(last_valid_row >= min_p) & (last_valid_row <= max_p)].index
                    df_filtered = data[saham_lolos]

                    if not df_filtered.empty:
                        if tipe == "Perubahan (%)":
                            df_final = (df_filtered.pct_change() * 100).round(2).T
                        else:
                            df_final = df_filtered.round(0).T
                        
                        df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                        
                        # Gabungkan dengan Nama Perusahaan
                        df_display = pd.merge(
                            df_emiten[['Kode Saham', 'Nama Perusahaan']], 
                            df_final, 
                            left_on='Kode Saham', 
                            right_index=True, 
                            how='inner'
                        )

                        st.success(f"Menampilkan {len(df_display)} saham")
                        st.dataframe(df_display, use_container_width=True)
                    else:
                        st.warning("Tidak ada saham di range harga ini.")
                else:
                    st.error("Data tidak ditemukan. Cek rentang tanggal.")
            except Exception as e:
                st.error(f"Error: {e}")

else:
    # JIKA FILE TIDAK DITEMUKAN: Tampilkan peringatan dan tombol upload cadangan
    st.error(f"⚠️ File '{FILE_NAME}' tidak ditemukan di GitHub!")
    st.info("Pastikan file tersebut berada di folder yang sama dengan app.py di GitHub.")
    
    # Tombol upload hanya muncul jika file di GitHub hilang
    uploaded_file = st.file_uploader("Atau upload manual di sini:", type=["xlsx", "csv"])
    if uploaded_file:
        df_emiten = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        st.success("File manual berhasil diunggah!")
        st.info("Segarkan (Refresh) halaman untuk mencoba membaca dari GitHub kembali.")
