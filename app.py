import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v13", layout="wide")
st.title("🎯 High Precision Smart Money Monitor")
st.markdown("---")

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
            if 'Kode Saham' in df.columns:
                df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK', '', regex=False)
                if 'Free Float' in df.columns:
                    df['Free Float'] = pd.to_numeric(df['Free Float'], errors='coerce').fillna(0)
                    if df['Free Float'].max() <= 1.0 and df['Free Float'].max() > 0:
                        df['Free Float'] = df['Free Float'] * 100
                return df, file_name
        except Exception as e:
            st.error(f"Gagal membaca file {file_name}: {e}")
    
    return pd.DataFrame({'Kode Saham': ['WINS', 'AKRA', 'TLKM'], 'Free Float': [30.0, 32.0, 47.0]}), "Default Mode"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI STYLING ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white'
        if num <= 40: return 'background-color: #008000; color: white'
    except: pass
    return ''

def to_excel_report(df_short, df_all):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_short.to_excel(writer, index=False, sheet_name='Shortlist_Ketat')
        df_all.to_excel(writer, index=False, sheet_name='Semua_Analisa')
    return output.getvalue()

# --- 4. LOGIKA ANALISA DENGAN PARAMETER "AND" KETAT ---
def get_signals_and_data(df_c, df_v, df_h, df_l, df_ref, min_vol_lot):
    results = []
    min_vol_lembar = min_vol_lot * 100
    ff_lookup = dict(zip(df_ref['Kode Saham'], df_ref['Free Float']))
    
    ihsg_c = df_c["^JKSE"].dropna() if "^JKSE" in df_c.columns else pd.Series()
    ihsg_perf = (ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20] if len(ihsg_c) >= 20 else 0

    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col): continue
        c, v, h, l = df_c[col].dropna(), df_v[col].dropna(), df_h[col].dropna(), df_l[col].dropna()
        if len(c) < 40: continue 
        
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        if avg_vol20 == 0 or pd.isna(avg_vol20) or avg_vol20 < min_vol_lembar: 
            continue

        rel_vol = v.iloc[-1] / avg_vol20
        p_change_today = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100
        daily_turnover = (c.iloc[-1] * v.iloc[-1]) / 1_000_000_000 # Turnover dlm Miliar

        # Kalkulasi MFI
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0.000001)).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf).replace([np.inf, -np.inf], np.nan).fillna(0)))
        
        last_mfi = mfi_series.iloc[-1] if not mfi_series.empty else 50.0
        mfi_change_5d = (last_mfi - mfi_series.iloc[-6]) if len(mfi_series) >= 6 else 0.0
        ma20 = c.rolling(20).mean().iloc[-1]

        # --- PARAMETER KETAT (LOGIKA AND) ---
        reasons = []
        
        # Kondisi A: High Conviction Accumulation (Volume Spike + Arus Uang Masuk)
        if rel_vol >= 2.0 and mfi_change_5d > 8.0:
            reasons.append("Big Money In (Vol & MFI Surge)")
        
        # Kondisi B: Bullish Breakout (Harga Tembus MA20 + Volume Konfirmasi)
        if c.iloc[-1] > ma20 and c.iloc[-2] <= ma20 and rel_vol > 1.5:
            reasons.append("Structural Breakout (Price & Vol)")
        
        # Kondisi C: Reversal (MFI Sangat Rendah tapi mulai Naik + Volume Bangun)
        if last_mfi < 35 and mfi_change_5d > 5.0 and rel_vol > 1.2:
            reasons.append("Potential Reversal (Low MFI Recovery)")

        ticker_name = str(col).replace('.JK','').upper()
        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        results.append({
            'Kode Saham': ticker_name,
            'Free Float (%)': float(ff_lookup.get(ticker_name, 0.0)),
            'MFI (14D)': float(last_mfi),
            'Price Change (%)': float(p_change_today),
            'Market RS': rs,
            'Above MA20': "YA" if c.iloc[-1] > ma20 else "TIDAK",
            'Last Price': int(c.iloc[-1]),
            'Rel Vol': float(rel_vol),
            'Turnover (M)': daily_turnover,
            'Shortlist Reasons': ", ".join(reasons) if reasons else ""
        })

    return pd.DataFrame(results)

# --- 5. UI SIDEBAR ---
st.sidebar.header("⚙️ Filter Ketat")
target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (Kosongkan = Semua):", options=target_list)

min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=100)
min_turnover = st.sidebar.number_input("Min Transaksi/Hari (Miliar Rp)", value=5.0) # Diperketat ke 5M
max_ff = float(st.sidebar.slider("Maximal Free Float (%)", 0.0, 100.0, 45.0)) # Diperketat ke 45%

today = date.today()
start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
end_d = st.sidebar.date_input("Tanggal Akhir", today)

btn_analisa = st.sidebar.button("🚀 MULAI SCANNING KETAT", use_container_width=True)

# --- 6. OUTPUT ---
if btn_analisa:
    with st.spinner('Memfilter saham high-probability...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_res = get_signals_and_data(df_c, df_v, df_h, df_l, df_emiten, 50000) # Min 50rb lot
            
            # Filter Dasar di UI
            df_res = df_res[
                (df_res['Last Price'] >= min_p) & 
                (df_res['Free Float (%)'] <= max_ff) &
                (df_res['Turnover (M)'] >= min_turnover)
            ]

            # Tampilan Shortlist
            st.subheader("💎 Saham Pilihan Utama (High Precision)")
            df_s = df_res[df_res['Shortlist Reasons'] != ""].sort_values('Rel Vol', ascending=False)
            
            if not df_s.empty:
                st.dataframe(
                    df_s.style.map(style_mfi, subset=['MFI (14D)'])
                    .format({
                        'Rel Vol': "{:.2f}x", 
                        'Turnover (M)': "{:.2f}B", 
                        'Free Float (%)': "{:.2f}%",
                        'Price Change (%)': "{:.2f}%",
                        'MFI (14D)': "{:.2f}"
                    }), 
                    use_container_width=True
                )
                
                # Visualisasi Chart Saham Teratas
                top_ticker = df_s.iloc[0]['Kode Saham']
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_c.index, y=df_c[f"{top_ticker}.JK"], name='Close'))
                fig.update_layout(title=f"Chart Harga: {top_ticker}", template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Tidak ada saham yang memenuhi kriteria kombinasi ketat hari ini.")

            st.markdown("---")
            st.subheader("🔍 Seluruh Database Analisa")
            st.dataframe(
                df_res.style.format({
                    'Rel Vol': "{:.2f}x", 
                    'Turnover (M)': "{:.2f}B",
                    'Price Change (%)': "{:.2f}%"
                }), 
                use_container_width=True, 
                height=400
            )

            excel_data = to_excel_report(df_s, df_res)
            st.sidebar.download_button(label="📥 Download Hasil", data=excel_data, file_name=f"Precision_Scan_{date.today()}.xlsx")
        else:
            st.error("Gagal menarik data.")
else:
    st.info(f"Screener v13 Ready. Menggunakan Database: {loaded_file}")
