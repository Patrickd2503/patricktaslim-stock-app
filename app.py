import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
import glob

st.set_page_config(page_title="Monitor Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# --- FUNGSI OTOMATIS MEMBACA EXCEL DI GITHUB ---
def load_data_from_github():
    # Mencari file Excel (.xlsx) yang ada kata 'Kode Saham' di folder GitHub
    files = glob.glob("*Kode Saham*.xlsx")
    if files:
        target_file = files[0]
        try:
            # Membaca excel menggunakan engine openpyxl
            df = pd.read_excel(target_file)
            return df, target_file
        except Exception as e:
            return None, str(e)
    return None, None

df_emiten, info_file = load_data_from_github()

# --- LOGIKA TAMPILAN ---
if df_emiten is not None:
    # JIKA EXCEL DITEMUKAN: Langsung tampilkan fitur utama
    st.sidebar.success(f"✅ Memuat File: {info_file}")
    
    st.sidebar.header("Filter & Konfigurasi")
    min_p, max_p = st.sidebar.slider("Rentang Harga (IDR)", 50, 15000, (50, 1500))
    tipe = st.sidebar.radio("Tampilan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=7))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Tarik Data"):
        with st.spinner('Mengambil data dari Yahoo Finance...'):
            # Ambil kolom Kode Saham
            if 'Kode Saham' in df_emiten.columns:
                tickers = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
                
                try:
                    data = yf.download(tickers, start=start_d, end=end_d, threads=True)['Close']
                    
                    if not data.empty:
                        last_valid = data.ffill().iloc[-1]
                        saham_lolos = last_valid[(last_valid >= min_p) & (last_valid <= max_p)].index
                        df_filtered = data[saham_lolos]

                        if not df_filtered.empty:
                            if tipe == "Perubahan (%)":
                                df_final = (df_filtered.pct_change() * 100).round(2).T
                            else:
                                df_final = df_filtered.round(0).T
                            
                            df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                            df_display = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_final, 
                                                 left_on='Kode Saham', right_index=True, how='inner')

                            st.success(f"Ditemukan {len(df_display)} saham.")
                            st.dataframe(df_display, use_container_width=True)
                        else:
                            st.warning("Tidak ada saham di range harga ini.")
                    else:
                        st.error("Data kosong untuk tanggal ini.")
                except Exception as e:
                    st.error(f"Error Yahoo Finance: {e}")
            else:
                st.error("Kolom 'Kode Saham' tidak ditemukan di file Excel Anda.")
else:
    # JIKA EXCEL TIDAK DITEMUKAN
    st.error("⚠️ File Excel 'Kode Saham' tidak terdeteksi di direktori GitHub.")
    st.info("Pastikan file .xlsx Anda sudah di-upload ke GitHub dan berada satu folder dengan app.py.")
