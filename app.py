import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

# Konfigurasi halaman
st.set_page_config(page_title="Monitor Saham BEI", layout="wide")

st.title("📊 Monitoring Saham BEI")
st.markdown("Aplikasi ini otomatis membaca daftar emiten dari GitHub Anda dan menarik data dari Yahoo Finance.")

# --- SETTING NAMA FILE ---
# Harus sama persis dengan yang ada di GitHub Anda
FILE_NAME = 'Kode Saham.xlsx - Sheet1.csv'

@st.cache_data
def load_emiten():
    if os.path.exists(FILE_NAME):
        return pd.read_csv(FILE_NAME)
    return None

df_emiten = load_emiten()

# --- SIDEBAR PENGATURAN ---
if df_emiten is not None:
    st.sidebar.header("Filter & Konfigurasi")
    
    # 1. Slider Range Harga
    min_p, max_p = st.sidebar.slider("Rentang Harga (IDR)", 50, 15000, (50, 1500))
    
    # 2. Tipe Data
    tipe = st.sidebar.radio("Tampilkan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    # 3. Rentang Tanggal
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=7))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Ambil Data Terbaru"):
        with st.spinner('Sedang menarik data 900+ emiten... Mohon tunggu sebentar.'):
            # Menyiapkan list ticker dengan akhiran .JK
            tickers = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
            
            # Menarik data (menggunakan chunk/batch agar lebih stabil)
            try:
                data = yf.download(tickers, start=start_d, end=end_d, threads=True)['Close']
                
                if not data.empty:
                    # Ambil harga terakhir untuk filter slider
                    last_valid_row = data.ffill().iloc[-1]
                    saham_lolos = last_valid_row[(last_valid_row >= min_p) & (last_valid_row <= max_p)].index
                    
                    df_filtered = data[saham_lolos]

                    if not df_filtered.empty:
                        if tipe == "Perubahan (%)":
                            df_final = (df_filtered.pct_change() * 100).round(2).T
                        else:
                            df_final = df_filtered.round(0).T
                        
                        # Gabungkan dengan Nama Perusahaan
                        df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                        df_display = pd.merge(
                            df_emiten[['Kode Saham', 'Nama Perusahaan']], 
                            df_final, 
                            left_on='Kode Saham', 
                            right_index=True, 
                            how='inner'
                        )

                        st.success(f"Ditemukan {len(df_display)} saham di range Rp{min_p} - Rp{max_p}")
                        st.dataframe(df_display, use_container_width=True)
                        
                        # Tombol Download
                        csv = df_display.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Download ke CSV", csv, "data_saham.csv", "text/csv")
                    else:
                        st.warning("Tidak ada saham yang masuk dalam kriteria range harga tersebut.")
                else:
                    st.error("Data tidak ditemukan. Coba pilih rentang tanggal yang lebih luas.")
            except Exception as e:
                st.error(f"Terjadi kendala saat menarik data: {e}")
else:
    st.error(f"File '{FILE_NAME}' tidak ditemukan di repository GitHub Anda.")
