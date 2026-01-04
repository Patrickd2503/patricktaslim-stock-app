import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta
import os
from io import BytesIO

st.set_page_config(page_title="Monitor Saham BEI Pro", layout="wide")
st.title("📊 Smart Monitor: Export to Excel")

# --- 1. FITUR CACHE ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    df = yf.download(tickers, start=start_date, end=end_date, threads=True, progress=False)
    return df['Close'], df['Volume']

# --- 2. LOAD DATA ---
def load_data_auto():
    POSSIBLE_FILES = ['Kode Saham.xlsx - Sheet1.csv', 'Kode Saham.xlsx', 'Kode_Saham.xlsx']
    for file_name in POSSIBLE_FILES:
        if os.path.exists(file_name):
            try:
                return (pd.read_csv(file_name) if file_name.endswith('.csv') else pd.read_excel(file_name)), file_name
            except: continue
    return None, None

df_emiten, nama_file_aktif = load_data_auto()

# --- 3. FUNGSI EXPORT EXCEL (MULTI-SHEET) ---
def to_excel_all(df_pct, df_prc, df_top):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Sheet 1: Shortlist
        if not df_top.empty:
            df_top.to_excel(writer, index=False, sheet_name='1. Top Picks Shortlist')
        
        # Sheet 2: Perubahan Persentase
        df_pct.to_excel(writer, index=False, sheet_name='2. Perubahan Persen')
        
        # Sheet 3: Harga Penutupan
        df_prc.to_excel(writer, index=False, sheet_name='3. Harga Harian IDR')
        
        # Format Kolom (Auto-fit sederhana)
        workbook = writer.book
        for sheet in writer.sheets.values():
            header_format = workbook.add_format({'bold': True, 'bg_color': '#0070C0', 'font_color': 'white'})
            sheet.set_column('A:B', 20) # Lebar kolom Kode & Nama
            sheet.set_column('C:C', 25) # Lebar kolom Analisa
    return output.getvalue()

# --- 4. LOGIKA ANALISA ---
def get_signals_and_shortlist(df_c, df_v):
    signals, shortlist = {}, []
    for col in df_c.columns:
        c, v = df_c[col].dropna(), df_v[col].dropna()
        if len(c) < 5: continue
        change_today = (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
        change_5d = (c.iloc[-1] - c.iloc[-5]) / c.iloc[-5]
        v_sma5 = v.rolling(5).mean().iloc[-1]
        v_ratio = v.iloc[-1] / v_sma5 if v_sma5 > 0 else 0
        ticker = col.replace('.JK','')
        
        status = "Normal"
        if abs(change_5d) < 0.02 and v_ratio > 1.2:
            status = f"💎 Akumulasi (V:{v_ratio:.1f})"
            if abs(change_today) <= 0.015 and 1.2 <= v_ratio <= 2.5:
                shortlist.append(ticker)
        elif change_5d > 0.05 and v_ratio > 1.0:
            status = f"🚀 Markup (V:{v_ratio:.1f})"
        elif change_5d < -0.05:
            status = "⛔ Distribusi"
        signals[ticker] = status
    return signals, shortlist

# --- 5. SIDEBAR & RENDER ---
if df_emiten is not None:
    st.sidebar.header("Konfigurasi")
    selected_tickers = st.sidebar.multiselect("Cari Kode:", options=sorted(df_emiten['Kode Saham'].dropna().unique().tolist()))
    min_p = st.sidebar.number_input("Harga Min", value=100)
    max_p = st.sidebar.number_input("Harga Max", value=300)
    tipe = st.sidebar.radio("Mode Tampilan:", ("Perubahan (%)", "Harga (IDR)", "Split View (Keduanya)"))
    
    today = date.today()
    start_d = st.sidebar.date_input("Mulai", today - timedelta(days=20))
    end_d = st.sidebar.date_input("Akhir", today)

    if st.sidebar.button("🚀 Jalankan Analisa"):
        with st.spinner('Menyiapkan data Excel...'):
            df_to_f = df_emiten[df_emiten['Kode Saham'].isin(selected_tickers)] if selected_tickers else df_emiten
            tickers_jk = [str(k).strip() + ".JK" for k in df_to_f['Kode Saham'].dropna().unique()]
            
            df_c_raw, df_v_raw = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
            
            if not df_c_raw.empty:
                df_c, df_v = df_c_raw.ffill(), df_v_raw.fillna(0)
                last_p = df_c.iloc[-1]
                saham_lolos = df_c.columns if selected_tickers else last_p[(last_p >= min_p) & (last_p <= max_p)].index
                
                df_f_c, df_f_v = df_c[saham_lolos], df_v[saham_lolos]
                signals_dict, shortlist_keys = get_signals_and_shortlist(df_f_c, df_f_v)
                df_sig = pd.DataFrame(list(signals_dict.items()), columns=['Kode Saham', 'Analisa Akumulasi'])

                def prepare_display(df_data, is_pct=True):
                    if is_pct:
                        df_f = (df_data.pct_change() * 100).applymap(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0%")
                    else:
                        df_f = df_data.applymap(lambda x: int(x) if pd.notnull(x) else 0)
                    df_f.index = df_f.index.strftime('%Y-%m-%d')
                    df_t = df_f.T
                    df_t.index = df_t.index.str.replace('.JK', '', regex=False)
                    m = pd.merge(df_emiten[['Kode Saham', 'Nama Perusahaan']], df_t, left_on='Kode Saham', right_index=True)
                    f = pd.merge(m, df_sig, on='Kode Saham', how='left')
                    cols = list(f.columns)
                    return f[[cols[0], cols[1], cols[-1]] + cols[2:-1]]

                # --- PROSES DATA UNTUK EXPORT ---
                df_all_pct = prepare_display(df_f_c, is_pct=True)
                df_all_prc = prepare_display(df_f_c, is_pct=False)
                df_top = df_all_pct[df_all_pct['Kode Saham'].isin(shortlist_keys)]

                # --- TOMBOL DOWNLOAD UTAMA ---
                st.success("✅ Analisa Selesai!")
                excel_file = to_excel_all(df_all_pct, df_all_prc, df_top)
                st.download_button(
                    label="📥 Download Data Lengkap (.xlsx)",
                    data=excel_file,
                    file_name=f'Analisa_Saham_BEI_{today}.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )

                st.markdown("---")
                
                # --- RENDER TAMPILAN (DASHBOARD) ---
                st.subheader("🎯 Shortlist Akumulasi")
                if not df_top.empty: st.dataframe(df_top, use_container_width=True)
                else: st.warning("Tidak ada shortlist.")

                if tipe in ["Perubahan (%)", "Split View (Keduanya)"]:
                    st.subheader("📈 Tabel Perubahan (%)")
                    st.dataframe(df_all_pct, use_container_width=True)

                if tipe in ["Harga (IDR)", "Split View (Keduanya)"]:
                    st.subheader("💰 Tabel Harga (IDR)")
                    st.dataframe(df_all_prc, use_container_width=True)
            else: st.error("Data gagal ditarik.")
