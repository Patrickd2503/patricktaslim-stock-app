import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os

st.set_page_config(page_title="Monitor Saham BEI Pro", layout="wide")
st.title("📊 Monitoring & Analisa Akumulasi Saham BEI")

# --- 1. FITUR CACHE ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    df = yf.download(tickers, start=start_date, end=end_date, threads=True)
    return df['Close'], df['Volume']

# --- 2. LOAD DATA EMITEN ---
POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']

def load_data_auto():
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                if file_name.endswith('.csv'):
                    return pd.read_csv(file_name), file_name
                else:
                    return pd.read_excel(file_name), file_name
            except: continue
    return None, None

df_emiten, nama_file_aktif = load_data_auto()

# --- 3. FUNGSI WARNA ---
def style_target(val):
    try:
        if isinstance(val, str):
            # Membersihkan simbol agar logika angka tetap jalan
            clean_val = val.replace('%', '').replace(',', '')
            num_val = float(clean_val)
        else: num_val = float(val)
        
        if num_val > 0: return 'background-color: rgba(144, 238, 144, 0.4)' 
        elif num_val < 0: return 'background-color: rgba(255, 182, 193, 0.4)' 
        elif num_val == 0: return 'background-color: rgba(255, 255, 0, 0.3)'   
    except: pass
    return ''

# --- 4. LOGIKA ANALISA AKUMULASI ---
def get_signals(df_c, df_v):
    signals = {}
    for col in df_c.columns:
        c = df_c[col].dropna()
        v = df_v[col].dropna()
        if len(c) < 5:
            signals[col.replace('.JK','')] = "Data Kurang"
            continue
        
        change_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_last = v.iloc[-1]
        
        if abs(change_5d) < 0.02 and v_last > (v_sma5 * 1.2):
            signals[col.replace('.JK','')] = "💎 Akumulasi Senyap"
        elif change_5d > 0.05 and v_last > v_sma5:
            signals[col.replace('.JK','')] = "🚀 Markup (Uptrend)"
        elif change_5d < -0.05:
            signals[col.replace('.JK','')] = "⛔ Distribusi/Oversold"
        else:
            signals[col.replace('.JK','')] = "Normal"
    return signals

# --- 5. SIDEBAR ---
if df_emiten is not None:
    st.sidebar.header("Filter & Konfigurasi")
    all_tickers = sorted(df_emiten['Kode Saham'].dropna().unique().tolist())
    selected_tickers = st.sidebar.multiselect("Cari Kode Saham:", options=all_tickers)

    st.sidebar.subheader("Rentang Harga (IDR)")
    min_price = st.sidebar.number_input("Harga Minimal", min_value=0, value=50)
    max_price = st.sidebar.number_input("Harga Maksimal", min_value=0, value=1500)
    
    tipe = st.sidebar.radio("Tampilan:", ("Harga Penutupan (IDR)", "Perubahan (%)", "Split View (Keduanya)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Mulai", today - timedelta(days=20))
    end_d = st.sidebar.date_input("Akhir", today)

    if st.sidebar.button("🚀 Tarik Data & Analisa"):
        with st.spinner('Menganalisa data pasar...'):
            if selected_tickers:
                df_to_fetch = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)]
                mode_pencarian = "kode"
            else:
                df_to_fetch = df_emiten
                mode_pencarian = "harga"
            
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_fetch['Kode Saham'].dropna().unique()]
            
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c_raw.empty:
                df_c = df_c_raw.ffill()
                df_v = df_v_raw.fillna(0)
                
                if mode_pencarian == "harga":
                    last_p = df_c.iloc[-1]
                    saham_lolos = last_p[(last_p >= min_price) & (last_p <= max_price)].index
                else:
                    saham_lolos = df_c.columns
                
                df_f_c = df_c[saham_lolos]
                df_f_v = df_v[saham_lolos]

                if not df_f_c.empty:
                    signals_dict = get_signals(df_f_c, df_f_v)
                    df_sig = pd.DataFrame(list(signals_dict.items()), columns=['Kode Saham', 'Analisa Akumulasi'])

                    def prepare_final(df_data, is_pct=True):
                        # Format Angka
                        if is_pct:
                            df_formatted = (df_data.pct_change() * 100).applymap(lambda x: f"{x:.1f}%".replace('.', ',') if pd.notnull(x) else "0,0%")
                        else:
                            df_formatted = df_data.applymap(lambda x: f"{int(x):,}" if pd.notnull(x) else "0")
                        
                        df_formatted.index = df_formatted.index.strftime('%d/%m/%Y')
                        df_t = df_formatted.T
                        df_t.index = df_t.index.str.replace('.JK', '', regex=False)
                        
                        # Gabungkan Nama Perusahaan
                        merged = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_t, left_on='Kode Saham', right_index=True)
                        # Gabungkan Sinyal
                        final = pd.merge(merged, df_sig, on='Kode Saham', how='left')
                        
                        # --- REORDER KOLOM (Pindahkan Analisa ke depan) ---
                        cols = list(final.columns)
                        # Struktur awal: [Kode, Nama, Tanggal1, Tanggal2..., Analisa]
                        # Pindahkan kolom terakhir (Analisa) ke posisi index 2
                        new_order = [cols[0], cols[1], cols[-1]] + cols[2:-1]
                        return final[new_order]

                    if tipe in ["Perubahan (%)", "Split View (Keduanya)"]:
                        st.subheader("📈 Perubahan Harga & Sinyal Akumulasi")
                        df_pct = prepare_final(df_f_c, is_pct=True)
                        # Pewarnaan hanya untuk kolom tanggal (mulai dari index 3)
                        st.dataframe(df_pct.style.applymap(style_target, subset=df_pct.columns[3:]), use_container_width=True)

                    if tipe in ["Harga Penutupan (IDR)", "Split View (Keduanya)"]:
                        st.subheader("💰 Harga Penutupan & Sinyal Akumulasi")
                        df_prc = prepare_final(df_f_c, is_pct=False)
                        st.dataframe(df_prc.style.applymap(style_target, subset=df_prc.columns[3:]), use_container_width=True)
                else:
                    st.warning("Saham tidak ditemukan.")
            else:
                st.error("Gagal mengambil data.")
else:
    st.error("⚠️ File daftar saham tidak ditemukan.")
