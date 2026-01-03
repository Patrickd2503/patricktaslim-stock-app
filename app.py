import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
import glob

st.set_page_config(page_title="Monitor Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# --- FUNGSI OTOMATIS MENCARI FILE ---
def find_and_load_data():
    # Mencari file yang mengandung kata 'Kode Saham' dan berakhiran .csv atau .xlsx
    files = glob.glob("*Kode Saham*.*")
    if files:
        target_file = files[0] # Ambil file pertama yang ditemukan
        try:
            if target_file.endswith('.csv'):
                return pd.read_csv(target_file), target_file
            else:
                return pd.read_excel(target_file), target_file
        except:
            return None, None
    return None, None

df_emiten, nama_file_ditemukan = find_and_load_data()

# --- LOGIKA TAMPILAN ---
if df_emiten is not None:
    # JIKA FILE DITEMUKAN: Langsung munculkan menu tanpa tombol upload
    st.sidebar.success(f"✅ Otomatis Memuat: {nama_file_ditemukan}")
    
    st.sidebar.header("Filter & Konfigurasi")
    min_p, max_p = st.sidebar.slider("Rentang Harga (IDR)", 50, 15000, (50, 1500))
    tipe = st.sidebar.radio("Tampilkan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=7))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Ambil Data Terbaru"):
        with st.spinner('Menarik data...'):
            # Menyiapkan ticker
            tickers = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
            
            try:
                data = yf.download(tickers, start=start_d, end=end_d, threads=True)['Close']
                
                if not data.empty:
                    last_valid = data.ffill().iloc[-1]
                    saham_lolos = last_valid[(last_valid >= min_p) & (last_valid <= max_p)].index
                    df_filtered = data[saham_lolos]

                    if not df_filtered.empty:
                        df_final = (df_filtered.pct_change() * 100).round(2).T if tipe == "Perubahan (%)" else df_filtered.round(0).T
                        df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                        
                        df_display = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_final, 
                                             left_on='Kode Saham', right_index=True, how='inner')

                        st.success(f"Menampilkan {len(df_display)} saham")
                        st.dataframe(df_display, use_container_width=True)
                    else:
                        st.warning("Tidak ada saham di range harga ini.")
                else:
                    st.error("Data kosong. Pilih rentang tanggal lain.")
            except Exception as e:
                st.error(f"Error: {e}")
else:
    # JIKA FILE TIDAK DITEMUKAN SAMA SEKALI
    st.error("⚠️ File daftar saham tidak ditemukan di GitHub!")
    st.info("Pastikan file 'Kode Saham.xlsx - Sheet1.csv' sudah di-upload ke GitHub di folder yang sama dengan app.py.")
    
    # Tombol upload manual (hanya sebagai cadangan)
    uploaded = st.file_uploader("Upload manual sebagai cadangan:", type=["xlsx", "csv"])
    if uploaded:
        df_emiten = pd.read_csv(uploaded) if uploaded.name.endswith('.csv') else pd.read_excel(uploaded)
        st.rerun()
