import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Dashboard Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# --- SIDEBAR PENGATURAN ---
st.sidebar.header("Konfigurasi & Filter")
uploaded_file = st.sidebar.file_uploader("1. Upload Kode Saham.xlsx", type=["xlsx", "csv"])

if uploaded_file:
    try:
        # Membaca file
        if uploaded_file.name.endswith('.csv'):
            df_emiten = pd.read_csv(uploaded_file)
        else:
            df_emiten = pd.read_excel(uploaded_file)
        
        if 'Kode Saham' in df_emiten.columns:
            # 2. Pengaturan Filter Range Harga (50 - 15.000)
            st.sidebar.subheader("Filter Harga")
            min_price, max_price = st.sidebar.slider(
                "Pilih Range Harga (IDR):", 
                50, 15000, (50, 1500) # Default setting awal 50 - 1500, tapi bisa digeser sampai 15000
            )

            # 3. Pilihan Tipe Data & Tanggal
            tipe_data = st.sidebar.radio("3. Tampilan Data:", ("Harga Penutupan (IDR)", "Kenaikan (%)"))
            
            today = date.today()
            # Default 7 hari ke belakang agar data selalu tersedia (menghindari hari libur)
            start_date = st.sidebar.date_input("4. Tanggal Mulai", today - timedelta(days=7))
            end_date = st.sidebar.date_input("5. Tanggal Akhir", today)

            if st.sidebar.button("Tarik & Filter Data"):
                with st.spinner('Sedang memproses data emiten...'):
                    # Menyiapkan list ticker
                    list_saham = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().tolist()]
                    
                    # Download data (Hanya kolom Close untuk efisiensi)
                    data = yf.download(list_saham, start=start_date, end=end_date, threads=True)['Close']
                    
                    if not data.empty:
                        # Ambil harga terakhir yang tersedia (baris paling bawah)
                        last_prices = data.iloc[-1] 
                        
                        # Filter saham berdasarkan range harga user
                        saham_lolos = last_prices[(last_prices >= min_price) & (last_prices <= max_price)].index
                        
                        df_filtered = data[saham_lolos]

                        if not df_filtered.empty:
                            if tipe_data == "Kenaikan (%)":
                                # Hitung perubahan persen dan transpose
                                df_final = (df_filtered.pct_change() * 100).round(2).T
                            else:
                                df_final = df_filtered.round(0).T
                            
                            # Bersihkan index untuk penggabungan nama perusahaan
                            df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                            
                            # Gabungkan dengan Nama Perusahaan
                            df_display = pd.merge(
                                df_emiten[['Kode Saham', 'Nama Perusahaan']], 
                                df_final, 
                                left_on='Kode Saham', 
                                right_index=True, 
                                how='inner'
                            )

                            st.success(f"Berhasil memuat {len(df_display)} saham dalam range Rp{min_price} - Rp{max_price}")
                            st.dataframe(df_display, use_container_width=True)
                        else:
                            st.warning(f"Tidak ada saham ditemukan di range Rp{min_price} - Rp{max_price}")
                    else:
                        st.error("Gagal menarik data. Pastikan bursa sedang buka pada tanggal tersebut.")
        else:
            st.error("Kolom 'Kode Saham' tidak ditemukan di file Anda.")
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Silakan upload file 'Kode Saham.xlsx' untuk memulai.")
