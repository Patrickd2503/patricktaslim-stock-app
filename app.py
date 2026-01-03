import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

st.set_page_config(page_title="Monitor Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# --- DAFTAR NAMA FILE YANG MUNGKIN ADA DI GITHUB ---
# Sistem akan mencoba satu per satu sampai ketemu
POSSIBLE_FILES = [
    'Kode Saham.xlsx - Sheet1.csv', 
    'Kode Saham.xlsx',
    'Kode_Saham.xlsx'
]

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

# --- LOGIKA TAMPILAN ---
if df_emiten is not None:
    # JIKA FILE KETEMU: Tombol Upload Hilang, Langsung Muncul Menu
    st.sidebar.success(f"✅ Menggunakan: {nama_file_aktif}")
    
    st.sidebar.header("Filter & Konfigurasi")
    min_p, max_p = st.sidebar.slider("Rentang Harga (IDR)", 50, 2000, (50, 1500))
    tipe = st.sidebar.radio("Tampilkan Data:", ("Harga Penutupan (IDR)", "Perubahan (%)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=7))
    end_d = st.sidebar.date_input("Tanggal Akhir", today)

    if st.sidebar.button("🚀 Tarik Data"):
        with st.spinner('Sedang mengambil data dari Yahoo Finance...'):
            if 'Kode Saham' in df_emiten.columns:
                # Menyiapkan ticker
                tickers = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
                
                try:
                    data = yf.download(tickers, start=start_d, end=end_d, threads=True)['Close']
                    
                    if not data.empty:
                        last_val = data.ffill().iloc[-1]
                        saham_lolos = last_val[(last_val >= min_p) & (last_val <= max_p)].index
                        df_filtered = data[saham_lolos]

                        if not df_filtered.empty:
                            df_final = (df_filtered.pct_change() * 100).round(2).T if tipe == "Perubahan (%)" else df_filtered.round(0).T
                            df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                            
                            df_display = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_final, 
                                                 left_on='Kode Saham', right_index=True, how='inner')

                            st.success(f"Ditemukan {len(df_display)} saham.")
                            st.dataframe(df_display, use_container_width=True)
                        else:
                            st.warning("Tidak ada saham di range harga ini.")
                    else:
                        st.error("Data kosong. Pilih rentang tanggal lain.")
                except Exception as e:
                    st.error(f"Error Yahoo Finance: {e}")
            else:
                st.error("Kolom 'Kode Saham' tidak ditemukan di file Anda.")
else:
    # JIKA FILE TIDAK KETEMU SAMA SEKALI DI GITHUB
    st.error("⚠️ File daftar saham tidak ditemukan di GitHub!")
    st.markdown(f"Sistem mencari file berikut namun tidak ada: `{POSSIBLE_FILES}`")
    st.info("Pastikan file tersebut di-upload ke GitHub sejajar dengan file app.py.")
    
    # Upload manual hanya muncul jika file di github benar-benar tidak ada
    uploaded = st.file_uploader("Upload manual:", type=["xlsx", "csv"])
    if uploaded:
        df_emiten = pd.read_csv(uploaded) if uploaded.name.endswith('.csv') else pd.read_excel(uploaded)
        st.rerun()

