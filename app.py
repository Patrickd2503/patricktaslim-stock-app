import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v17", layout="wide")
st.title("🛡️ Full-Feature Conservative Scanner")
st.markdown("### Fokus: Akumulasi Awal, Anti-Pucuk & Full Sidebar Control")

# --- 1. FITUR CACHE DATA ---
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = start_date - timedelta(days=450) 
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low']
        else:
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']]
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 2. LOAD DATABASE EMITEN ---
def load_data_auto():
    file_name = 'FreeFloat.xlsx'
    if os.path.exists(file_name):
        try: 
            df = pd.read_excel(file_name)
            df.columns = df.columns.str.strip()
            df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK', '', regex=False)
            if 'Free Float' in df.columns:
                df['Free Float'] = pd.to_numeric(df['Free Float'], errors='coerce').fillna(0)
                if df['Free Float'].max() <= 1.0:
                    df['Free Float'] = df['Free Float'] * 100
            return df, file_name
        except: pass
    return pd.DataFrame({'Kode Saham': ['TLKM', 'ASII', 'BBRI'], 'Free Float': [45.0, 49.0, 43.0]}), "Default Mode"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI EXPORT ---
def to_excel_report(df_short, df_all):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if not df_short.empty:
            df_short.to_excel(writer, index=False, sheet_name='Shortlist_Pilihan')
        df_all.to_excel(writer, index=False, sheet_name='Semua_Analisa')
    return output.getvalue()

# --- 4. LOGIKA ANALISA EARLY-BIRD ---
def get_analysis_data(df_c, df_v, df_h, df_l, df_ref, min_vol_lot):
    results = []
    ff_lookup = dict(zip(df_ref['Kode Saham'], df_ref['Free Float']))
    
    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 40: continue 
        
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        if avg_vol20 < (min_vol_lot * 100): continue
        
        rel_vol = v.iloc[-1] / avg_vol20
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        turnover = (c.iloc[-1] * v.iloc[-1]) / 1_000_000_000

        # RSI untuk Anti-Pucuk
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs_idx = gain / (loss + 0.000001)
        rsi = 100 - (100 / (1 + rs_idx.iloc[-1]))

        # MFI (Money Flow Index)
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0.000001)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf).fillna(0)))
        last_mfi = mfi_series.iloc[-1]
        mfi_change_5d = last_mfi - mfi_series.iloc[-6] if len(mfi_series) > 6 else 0
        ma20 = c.rolling(20).mean().iloc[-1]

        # --- LOGIKA SHORTLIST (AND) ---
        reasons = []
        # Syarat "Early Bird": RSI < 65 dan Kenaikan harga harian < 8%
        is_early = rsi < 65 and p_change < 8.0

        if is_early:
            if rel_vol >= 2.5 and mfi_change_5d > 12.0:
                reasons.append("Strong Acc: Low Risk Entry")
            elif rel_vol >= 1.8 and c.iloc[-1] > ma20 and c.iloc[-2] <= ma20:
                reasons.append("MA20 Breakout: Trend Start")

        ticker_name = str(col).replace('.JK','').upper()
        results.append({
            'Kode Saham': ticker_name,
            'Free Float (%)': float(ff_lookup.get(ticker_name, 0.0)),
            'Last Price': int(c.iloc[-1]),
            'Price Change (%)': p_change,
            'RSI (14D)': rsi,
            'MFI (14D)': last_mfi,
            'Rel Vol': rel_vol,
            'Turnover (M)': turnover,
            'Shortlist Reasons': ", ".join(reasons) if reasons else ""
        })

    return pd.DataFrame(results)

# --- 5. SIDEBAR (SEMUA MENU DIKEMBALIKAN) ---
st.sidebar.header("⚙️ Kontrol Navigasi")
target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (Kosong = Semua):", options=target_list)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Filter Harga & Likuiditas")
min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=100)
max_p = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=50000)
min_turnover = st.sidebar.number_input("Min Transaksi/Hari (Miliar)", value=10.0)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Proteksi Pucuk")
max_rsi = st.sidebar.slider("Max RSI (Anti Overbought)", 30, 85, 65)
max_ff = st.sidebar.slider("Max Free Float (%)", 0, 100, 35)

st.sidebar.markdown("---")
today = date.today()
start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
end_d = st.sidebar.date_input("Tanggal Akhir", today)

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA PENUH", use_container_width=True)

# --- 6. OUTPUT & DASHBOARD ---
if btn_analisa:
    with st.spinner('Menghitung data pasar...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_res = get_analysis_data(df_c, df_v, df_h, df_l, df_emiten, min_vol_lot)
            
            if not df_res.empty:
                # Filter berdasarkan Sidebar
                df_res = df_res[
                    (df_res['Last Price'] >= min_p) & 
                    (df_res['Last Price'] <= max_p) &
                    (df_res['Turnover (M)'] >= min_turnover) &
                    (df_res['Free Float (%)'] <= max_ff) &
                    (df_res['RSI (14D)'] <= max_rsi)
                ]

            st.subheader("💎 Shortlist: Saham Akumulasi Area Bawah")
            df_s = df_res[df_res['Shortlist Reasons'] != ""].sort_values('Rel Vol', ascending=False)
            
            if not df_s.empty:
                st.dataframe(
                    df_s.style.format({
                        'Price Change (%)': "{:.2f}%",
                        'RSI (14D)': "{:.2f}",
                        'MFI (14D)': "{:.2f}",
                        'Rel Vol': "{:.2f}x",
                        'Turnover (M)': "{:.2f}B"
                    }), use_container_width=True
                )
                
                # Chart Interaktif
                top_t = df_s.iloc[0]['Kode Saham']
                fig = go.Figure(data=[go.Candlestick(x=df_c.index, open=df_c[f"{top_t}.JK"]*0.99, high=df_h[f"{top_t}.JK"], low=df_l[f"{top_t}.JK"], close=df_c[f"{top_t}.JK"])])
                fig.update_layout(title=f"Analisis Teknikal: {top_t}", template="plotly_dark", height=450)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Tidak ada saham yang memenuhi kriteria Early-Bird hari ini.")

            st.markdown("---")
            st.subheader("🔍 Database Hasil Screening Seluruhnya")
            st.dataframe(
                df_res.style.format({
                    'Price Change (%)': "{:.2f}%",
                    'RSI (14D)': "{:.2f}",
                    'Rel Vol': "{:.2f}x",
                    'Turnover (M)': "{:.2f}B"
                }), use_container_width=True, height=400
            )

            # Tombol Download di Sidebar
            excel_data = to_excel_report(df_s, df_res)
            st.sidebar.download_button(label="📥 Download Excel", data=excel_data, file_name=f"Full_Analisa_{date.today()}.xlsx")
        else:
            st.error("Data gagal ditarik dari server Yahoo Finance.")
else:
    st.info(f"Screener Full v17 Siap. Database: {loaded_file}")
