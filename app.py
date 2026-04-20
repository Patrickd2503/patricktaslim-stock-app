import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import pandas_ta as pta
import streamlit.components.v1 as components

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI v16 + Chart", layout="wide")
st.title("🚀 Smart Money Monitor v16 – Pre-Breakout Radar")

st.markdown("""
**Update v16.1:**
- ✅ Semua fitur v16 (Early Momentum Score & Pre-Breakout Watch)
- 🆕 **Integrated TradingView Chart**: Lihat grafik teknikal langsung di dalam aplikasi tanpa pindah tab.
""")

# ─────────────────────────────────────────────
# 1. FUNGSI ANALISIS & DATA
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_yf_data(tickers, start_date, end_date):
    data = yf.download(tickers, start=start_date, end=end_date, group_by='ticker', progress=False)
    return data

def calculate_metrics(df, ticker):
    try:
        # Basic Technicals
        df['MA20'] = pta.sma(df['Close'], length=20)
        df['RSI'] = pta.rsi(df['Close'], length=14)
        
        # MFI Calculation
        df['MFI'] = pta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
        df['MFI_5D_Ago'] = df['MFI'].shift(5)
        mfi_change = df['MFI'].iloc[-1] - df['MFI_5D_Ago'].iloc[-1] if not pd.isna(df['MFI_5D_Ago'].iloc[-1]) else 0
        
        # ADX Calculation
        adx_df = pta.adx(df['High'], df['Low'], df['Close'], length=14)
        adx_val = adx_df['ADX_14'].iloc[-1]
        di_plus = adx_df['DMP_14'].iloc[-1]
        di_minus = adx_df['DMN_14'].iloc[-1]
        adx_prev = adx_df['ADX_14'].shift(1).iloc[-1]
        
        # Volume Analysis
        avg_vol_20 = df['Volume'].rolling(20).mean().iloc[-1]
        rel_vol = df['Volume'].iloc[-1] / avg_vol_20 if avg_vol_20 > 0 else 0
        
        # Trend Status
        above_ma20 = df['Close'].iloc[-1] > df['MA20'].iloc[-1]
        is_breakout = df['Close'].iloc[-1] > df['High'].shift(1).rolling(20).max().iloc[-2]
        
        # --- EARLY MOMENTUM SCORE (0-10) ---
        score = 0
        if mfi_change > 15: score += 3
        if adx_val > adx_prev: score += 2
        if above_ma20: score += 2
        if df['RSI'].iloc[-1] > 50: score += 1
        if di_plus > di_minus: score += 2
        
        return {
            "Last Price": df['Close'].iloc[-1],
            "MFI (14D)": round(df['MFI'].iloc[-1], 2),
            "MFI Change 5D": round(mfi_change, 2),
            "ADX Strength": round(adx_val, 2),
            "ADX Trend": "Rising" if adx_val > adx_prev else "Falling",
            "Rel Vol (20D)": round(rel_vol, 2),
            "Above MA20": "YA" if above_ma20 else "TIDAK",
            "20D Breakout": "YA" if is_breakout else "TIDAK",
            "Early Momentum Score": score,
            "Status": "🔭 Watch" if (score >= 7 and not is_breakout) else "-"
        }
    except:
        return None

# ─────────────────────────────────────────────
# 2. TRADINGVIEW WIDGET COMPONENT
# ─────────────────────────────────────────────
def tradingview_chart(symbol):
    # Format symbol untuk TV (contoh: BBCA.JK -> IDX:BBCA)
    tv_symbol = f"IDX:{symbol.replace('.JK', '')}"
    
    chart_html = f"""
    <div class="tradingview-widget-container" style="height:500px;width:100%">
      <div id="tradingview_df382" style="height:500px;width:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{tv_symbol}",
        "interval": "D",
        "timezone": "Asia/Jakarta",
        "theme": "light",
        "style": "1",
        "locale": "id",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_df382"
      }});
      </script>
    </div>
    """
    components.html(chart_html, height=520)

# ─────────────────────────────────────────────
# 3. SIDEBAR & CONTROL
# ─────────────────────────────────────────────
st.sidebar.header("Filter Parameter")
tickers_input = st.sidebar.text_area("List Ticker (pisahkan koma)", "ADCP.JK,CASH.JK,PURI.JK,MDIA.JK,KOTA.JK,BAPA.JK")
min_score = st.sidebar.slider("Minimum Early Momentum Score", 0, 10, 6)

if st.sidebar.button("Run Analysis"):
    ticker_list = [t.strip() for t in tickers_input.split(",")]
    start_date = date.today() - timedelta(days=100)
    end_date = date.today()
    
    with st.spinner("Menganalisis data pasar..."):
        all_data = fetch_yf_data(ticker_list, start_date, end_date)
        results = []
        
        for ticker in ticker_list:
            if ticker in all_data:
                df_ticker = all_data[ticker].dropna()
                if not df_ticker.empty:
                    metrics = calculate_metrics(df_ticker, ticker)
                    if metrics:
                        metrics['Kode'] = ticker
                        results.append(metrics)
        
        df_res = pd.DataFrame(results)
        
        # ─────────────────────────────────────────────
        # 4. DISPLAY TABLE DENGAN CHART TRIGGER
        # ─────────────────────────────────────────────
        if not df_res.empty:
            # Reorder columns
            cols = ['Kode', 'Last Price', 'Early Momentum Score', 'Status', 'MFI Change 5D', 'ADX Trend', 'Rel Vol (20D)', 'Above MA20', '20D Breakout']
            df_res = df_res[cols]
            
            st.subheader("📋 Hasil Screening")
            
            # Layouting: Baris per Baris dengan tombol ekspansi
            for index, row in df_res.iterrows():
                with st.expander(f"{'🔥' if row['Early Momentum Score'] >= 8 else '🔍'} {row['Kode']} - Score: {row['Early Momentum Score']} | {row['Status']}"):
                    col_info, col_chart = st.columns([1, 2])
                    
                    with col_info:
                        st.write(f"**Price:** {row['Last Price']}")
                        st.write(f"**MFI Change:** {row['MFI Change 5D']}")
                        st.write(f"**Rel Vol:** {row['Rel Vol (20D)']}x")
                        st.write(f"**Above MA20:** {row['Above MA20']}")
                        st.write(f"**Breakout:** {row['20D Breakout']}")
                        
                    with col_chart:
                        # Panggil widget TradingView
                        tradingview_chart(row['Kode'])
        else:
            st.warning("Tidak ada data yang cocok dengan kriteria.")

# --- FOOTER ---
st.markdown("---")
st.caption("v16.1 - Data source: Yahoo Finance & TradingView Widget")
