import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v16", layout="wide")
st.title("🛡️ Conservative Smart Money Scanner")
st.markdown("### Fokus: Akumulasi Awal & Anti-Pucuk")

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
        df_short.to_excel(writer, index=False, sheet_name='Shortlist_Pilihan')
        df_all.to_excel(writer, index=False, sheet_name='Semua_Analisa')
    return output.getvalue()

# --- 4. LOGIKA ANALISA CONSERVATIVE ---
def get_conservative_signals(df_c, df_v, df_h, df_l, df_ref, min_vol_lot):
    results = []
    ff_lookup = dict(zip(df_ref['Kode Saham'], df_ref['Free Float']))
    
    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 40: continue 
        
        # Kalkulasi Dasar
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        if avg_vol20 < (min_vol_lot * 100): continue
        
        rel_vol = v.iloc[-1] / avg_vol20
        p_change = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        turnover = (c.iloc[-1] * v.iloc[-1]) / 1_000_000_000

        # RSI (Relative Strength Index) untuk deteksi Overbought
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs_idx = gain / loss
        rsi = 100 - (100 / (1 + rs_idx.iloc[-1])) if not pd.isna(rs_idx.iloc[-1]) else 50

        # Money Flow Index (MFI)
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0.000001)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf).fillna(0)))
        last_mfi = mfi_series.iloc[-1]
        mfi_change_5d = last_mfi - mfi_series.iloc[-6] if len(mfi_series) > 6 else 0
        
        ma20 = c.rolling(20).mean().iloc[-1]

        # --- FILTER LOGIC: CONSERVATIVE & ANTI-PUCUK ---
        reasons = []
        
        # SYARAT KEAMANAN:
        # 1. RSI < 65 (Belum Jenuh Beli)
        # 2. Price Change hari ini < 7% (Belum terlanjur terbang tinggi)
        is_safe_entry = rsi < 65 and p_change < 7.0

        if is_safe_entry:
            # Kondisi A: Akumulasi Kuat di Area Bawah/Samping
            if rel_vol >= 2.5 and mfi_change_5d > 12.0:
                reasons.append("Early Acc: Extreme Vol + Money Flow")
            
            # Kondisi B: Fresh Breakout MA20
            elif rel_vol >= 1.8 and c.iloc[-1] > ma20 and c.iloc[-2] <= ma20 and last_mfi < 60:
                reasons.append("Fresh Breakout: New Trend Confirmed")

        if reasons:
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
                'Status': ", ".join(reasons)
            })

    return pd.DataFrame(results)

# --- 5. UI SIDEBAR ---
st.sidebar.header("⚙️ Proteksi Modal")
target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (Kosong = Semua):", options=target_list)

min_turnover = st.sidebar.number_input("Min Transaksi/Hari (Miliar)", value=10.0) # Naikkan ke 10M untuk keamanan
max_ff = st.sidebar.slider("Max Free Float (%)", 0, 100, 35) # Bandar lebih suka FF kecil

today = date.today()
start_d = today - timedelta(days=30)
end_d = today

btn_analisa = st.sidebar.button("🚀 SCAN SAHAM PILIHAN", use_container_width=True)

# --- 6. OUTPUT ---
if btn_analisa:
    with st.spinner('Memfilter anomali yang belum pucuk...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_res = get_conservative_signals(df_c, df_v, df_h, df_l, df_emiten, 50000)
            
            if not df_res.empty:
                # Filter tambahan dari Sidebar
                df_final = df_res[
                    (df_res['Turnover (M)'] >= min_turnover) & 
                    (df_res['Free Float (%)'] <= max_ff)
                ].sort_values('Rel Vol', ascending=False)
                
                if not df_final.empty:
                    st.success(f"Ditemukan {len(df_final)} Saham Potensial yang Belum Overbought")
                    st.dataframe(
                        df_final.style.format({
                            'Price Change (%)': "{:.2f}%",
                            'RSI (14D)': "{:.2f}",
                            'MFI (14D)': "{:.2f}",
                            'Rel Vol': "{:.2f}x",
                            'Turnover (M)': "{:.2f}B"
                        }), 
                        use_container_width=True
                    )
                    
                    # Visualisasi Chart
                    top_ticker = df_final.iloc[0]['Kode Saham']
                    fig = go.Figure(data=[go.Candlestick(
                        x=df_c.index,
                        open=df_h[f"{top_ticker}.JK"]*0.99, # Simulasi harga open
                        high=df_h[f"{top_ticker}.JK"],
                        low=df_l[f"{top_ticker}.JK"],
                        close=df_c[f"{top_ticker}.JK"]
                    )])
                    fig.update_layout(title=f"Price Action: {top_ticker}", template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Tidak ada saham yang lolos kriteria keamanan (Mungkin market sudah terlalu 'pucuk').")
            else:
                st.info("Tidak ditemukan anomali volume pada saham yang harganya masih rendah.")

            excel_data = to_excel_report(df_final if 'df_final' in locals() else pd.DataFrame(), df_res)
            st.sidebar.download_button(label="📥 Download Analisa", data=excel_data, file_name=f"Conservative_Scan_{date.today()}.xlsx")
else:
    st.info(f"Screener v16 (Early-Bird) Siap. Menggunakan Database: {loaded_file}")
