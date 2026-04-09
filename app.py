import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date, timedelta
import os
from io import BytesIO

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI Ultra v12", layout="wide")
st.title("🎯 Smart Money Monitor: Akumulasi & Visualisasi")

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
                else:
                    df['Free Float'] = 0
                return df, file_name
        except Exception as e:
            st.error(f"Gagal membaca file {file_name}: {e}")
    
    default_data = pd.DataFrame({'Kode Saham': ['WINS', 'CNKO', 'KOIN'], 'Free Float': [30.0, 45.0, 20.0]})
    return default_data, "Default Mode"

df_emiten, loaded_file = load_data_auto()

# --- 3. FUNGSI STYLING & EXPORT ---
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white'
        if num <= 40: return 'background-color: #008000; color: white'
    except: pass
    return ''

def style_rel_vol(val):
    try:
        num = float(val)
        if num >= 2.0: return 'background-color: #00cc00; color: white'
        if num >= 1.5: return 'background-color: #66ff66;'
    except: pass
    return ''

def to_excel_report(df_short, df_all):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_short.to_excel(writer, index=False, sheet_name='Shortlist')
        df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
    return output.getvalue()

# --- 4. LOGIKA ANALISA ---
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
        daily_turnover = c.iloc[-1] * v.iloc[-1]

        # Perbaikan Error Handling MFI (Menghindari DivByZero)
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = (mf.where(tp > tp.shift(1), 0)).rolling(14).sum()
        neg_mf = (mf.where(tp < tp.shift(1), 0.000001)).rolling(14).sum()
        
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf).replace([np.inf, -np.inf], np.nan).fillna(0)))
        last_mfi = mfi_series.iloc[-1] if not mfi_series.empty else 50.0
        mfi_change_5d = (last_mfi - mfi_series.iloc[-6]) if len(mfi_series) >= 6 else 0.0

        ma20 = c.rolling(20).mean().iloc[-1]
        is_above_ma20 = "YA" if c.iloc[-1] > ma20 else "TIDAK"

        pva = "Neutral"
        if p_change_today > 0.8 and rel_vol > 1.6: pva = "Strong Bullish Vol"
        elif p_change_today > 0.4 and rel_vol > 1.3: pva = "Bullish Vol"
        elif p_change_today < -0.6 and rel_vol > 1.5: pva = "Bearish Vol"

        ticker_name = str(col).replace('.JK','').upper()
        stock_perf = (c.iloc[-1] - c.iloc[-20]) / c.iloc[-20] if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        reasons = []
        if rel_vol >= 1.8 and p_change_today > 0.5: reasons.append("High Rel Vol + Price Up")
        if is_above_ma20 == "YA" and last_mfi < 55: reasons.append("Above MA20 + MFI Fresh")
        if mfi_change_5d > 3.5: reasons.append("MFI Rising")

        results.append({
            'Kode Saham': ticker_name,
            'Free Float (%)': float(ff_lookup.get(ticker_name, 0.0)),
            'MFI (14D)': float(last_mfi),
            'PVA': pva,
            'Market RS': rs,
            'Above MA20': is_above_ma20,
            'Last Price': int(c.iloc[-1]),
            'Rel Vol': float(rel_vol),
            'Turnover (M)': daily_turnover / 1_000_000_000,
            'AvgVol20 (Lot)': int(avg_vol20 / 100),
            'Shortlist Reasons': ", ".join(reasons) if reasons else ""
        })

    return pd.DataFrame(results)

# --- 5. UI SIDEBAR ---
st.sidebar.header("⚙️ Konfigurasi")
target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (Kosongkan = Semua):", options=target_list)

min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=50000)
min_turnover = st.sidebar.number_input("Min Transaksi/Hari (Miliar Rp)", value=1.0)
max_ff = float(st.sidebar.slider("Maximal Free Float (%)", 0.0, 100.0, 100.0))

today = date.today()
start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
end_d = st.sidebar.date_input("Tanggal Akhir", today)

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True)

# --- 6. OUTPUT & VISUALISASI ---
if btn_analisa:
    with st.spinner('Menganalisa market...'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)
        
        if not df_c.empty:
            df_res = get_signals_and_data(df_c, df_v, df_h, df_l, df_emiten, min_vol_lot)
            
            if not df_res.empty:
                df_res = df_res[
                    (df_res['Last Price'] >= min_p) & 
                    (df_res['Last Price'] <= max_p) & 
                    (df_res['Free Float (%)'] <= max_ff) &
                    (df_res['Turnover (M)'] >= min_turnover)
                ]

            st.subheader("🔥 Smart Money Shortlist")
            df_s = df_res[df_res['Shortlist Reasons'] != ""].sort_values('Rel Vol', ascending=False)
            
            if not df_s.empty:
                st.dataframe(df_s.style.map(style_mfi, subset=['MFI (14D)'])
                             .map(style_rel_vol, subset=['Rel Vol'])
                             .format({'Rel Vol': "{:.2f}x", 'Turnover (M)': "{:.2f}B", 'Free Float (%)': "{:.2f}%"}), 
                             use_container_width=True)
                
                # Visualisasi: Chart Interaktif
                st.markdown("---")
                top_ticker = df_s.iloc[0]['Kode Saham']
                st.subheader(f"📈 Visual Analisis: {top_ticker}")
                ticker_full = f"{top_ticker}.JK"
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_c.index, y=df_c[ticker_full], mode='lines', name='Price', line=dict(color='#00ff00')))
                fig.update_layout(title=f"Trend Harga {top_ticker}", template="plotly_dark", height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Tidak ada saham yang memenuhi kriteria akumulasi.")

            st.markdown("---")
            st.subheader("🔍 Database Hasil Screening")
            # FIX: Gunakan .style.format() untuk menghindari AttributeError
            st.dataframe(
                df_res.style.format({
                    'Rel Vol': "{:.2f}x", 
                    'Turnover (M)': "{:.2f}B",
                    'Free Float (%)': "{:.2f}%",
                    'MFI (14D)': "{:.2f}"
                }), 
                use_container_width=True, 
                height=400
            )

            excel_data = to_excel_report(df_s, df_res)
            st.sidebar.download_button(label="📥 Download Excel", data=excel_data, file_name=f"Analisa_{date.today()}.xlsx")
        else:
            st.error("Data tidak ditemukan.")
else:
    st.info(f"Screener siap. Database: {loaded_file}")
