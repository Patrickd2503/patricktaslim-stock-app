import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Dashboard Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# Sidebar untuk pengaturan
st.sidebar.header("Konfigurasi")
uploaded_file = st.sidebar.file_uploader("1. Upload Kode Saham.xlsx", type=["xlsx", "csv"])

if uploaded_file:
    # Membaca file
    try:
        if uploaded_file.name.endswith('.csv'):
            df_emiten = pd.read_csv(uploaded_file)
        else:
            df_emiten = pd.read_excel(uploaded_file)
        
        # Cek apakah kolom 'Kode Saham' ada
        if 'Kode Saham' in df_emiten.columns:
            list_saham = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().tolist()]
            
            # Pilihan Tipe Data & Tanggal
            tipe_data = st.sidebar.radio("2. Pilih Tampilan:", ("Harga Penutupan (IDR)", "Kenaikan (%)"))
            start_date = st.sidebar.date_input("3. Tanggal Mulai", date.today() - timedelta(days=7))
            end_date = st.sidebar.date_input("4. Tanggal Akhir", date.today())

            if st.sidebar.button("Tarik Data"):
                with st.spinner('Mengambil data dari Yahoo Finance...'):
                    # Download data
                    data = yf.download(list_saham, start=start_date, end=end_date)
                    
                    # Mengambil Close price (cek struktur kolom yfinance)
                    if not data.empty:
                        # Jika kolom multi-index (Ticker di bawah Close)
                        if 'Close' in data.columns:
                            df_close = data['Close']
                        else:
                            df_close = data

                        # Hitung persen jika dipilih
                        if tipe_data == "Kenaikan (%)":
                            df_hasil = (df_close.pct_change() * 100).round(2)
                        else:
                            df_hasil = df_close.round(0)

                        # Tampilkan hasil
                        st.subheader(f"Hasil Data: {tipe_data}")
                        st.dataframe(df_hasil.T, use_container_width=True)
                    else:
                        st.error("Data tidak ditemukan untuk rentang tanggal tersebut. Coba pilih tanggal yang lebih lama (Market tutup di hari libur/akhir pekan).")
        else:
            st.error("Kolom 'Kode Saham' tidak ditemukan dalam file. Pastikan header kolom tertulis 'Kode Saham'.")
    except Exception as e:
        st.error(f"Terjadi kesalahan saat membaca file: {e}")
else:
    st.info("Silakan upload file 'Kode Saham.xlsx' untuk memulai.")
