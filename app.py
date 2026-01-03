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
        # Menangani logika warna untuk string persen (8,7%)
        if isinstance(val, str) and '%' in val:
            num_val = float(val.replace('%', '').replace(',', '.'))
        else:
            num_val = float(val)
            
        if num_val > 0:
            return 'background-color: rgba(144, 238, 144, 0.4)' # Hijau Muda
        elif num_val < 0:
            return 'background-color: rgba(255, 182, 193, 0.4)' # Merah Muda
        elif num_val == 0:
            return 'background-color: rgba(255, 255, 0, 0.3)'   # Kuning
    except:
        pass
    return ''

# --- LOGIKA TAMPILAN ---
if df_emiten is not None:
    st.sidebar.success(f"✅ Menggunakan: {nama_file_aktif}")
    
    st.sidebar.header("Filter & Konfigurasi")
    
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
            tickers = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].dropna().unique()]
            data = yf.download(tickers, start=start_d, end=end_d, threads=True)['Close']
            
            if not data.empty:
                data_filled = data.ffill()
                last_val = data_filled.iloc[-1]
                
                saham_lolos = last_val[(last_val >= min_price) & (last_val <= max_price)].index
                df_filtered = data_filled[saham_lolos]

                if not df_filtered.empty:
                    # 1. FORMAT TANGGAL DI KOLOM (Ubah ke DD/MM/YYYY)
                    df_filtered.columns = [c.strftime('%d/%m/%Y') for c in df_filtered.columns]

                    if tipe == "Perubahan (%)":
                        df_raw = (df_filtered.pct_change() * 100)
                        # Format 1 desimal dengan koma dan %
                        df_final = df_raw.applymap(lambda x: f"{x:.1f}%".replace('.', ',') if pd.notnull(x) else "0,0%")
                        df_final = df_final.T
                    else:
                        df_final = df_filtered.round(0).T
                    
                    df_final.index = df_final.index.str.replace('.JK', '', regex=False)
                    
                    df_display = pd.merge(
                        df_emiten[['Kode Saham', 'Nama Perusahaan']], 
                        df_final, 
                        left_on='Kode Saham', 
                        right_index=True, 
                        how='inner'
                    )

                    cols_to_style = df_display.columns[2:]
                    styled_df = df_display.style.applymap(style_target, subset=cols_to_style)

                    st.success(f"Ditemukan {len(df_display)} saham.")
                    st.dataframe(styled_df, use_container_width=True)
                else:
                    st.warning("Tidak ada saham di range harga ini.")
            else:
                st.error("Data kosong. Pilih rentang tanggal lain.")
else:
    st.error("⚠️ File daftar saham tidak ditemukan di GitHub!")
