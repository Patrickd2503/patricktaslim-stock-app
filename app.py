import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO, StringIO
import pandas_ta as pta
import requests
import base64
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
from bs4 import BeautifulSoup

# =====================================================
# BROKER SUMMARY MODULE — EMBEDDED
# =====================================================

SMART_MONEY_BROKERS = {"OD", "ES", "HD", "AK", "ZP", "BK", "AI", "AZ", "MG", "CP", "RF", "YJ", "RX", "FS", "DX"}
RETAIL_BROKERS = {"YP", "XC", "CC", "KK", "SQ", "XL", "GW", "PD", "DH", "FZ"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Referer": "https://rtiindonesia.com/",
}

def _categorize_broker(code: str) -> str:
    code = str(code).upper().strip()
    if code in SMART_MONEY_BROKERS:
        return "smart_money"
    elif code in RETAIL_BROKERS:
        return "retail"
    return "unknown"

def _normalize_broker_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    col_map = {
        "broker": "broker_code", "kode": "broker_code", "code": "broker_code",
        "buy lot": "buy_lot", "lot beli": "buy_lot", "beli (lot)": "buy_lot",
        "sell lot": "sell_lot", "lot jual": "sell_lot", "jual (lot)": "sell_lot",
        "net lot": "net_lot", "net (lot)": "net_lot",
        "buy value": "buy_value", "nilai beli": "buy_value",
        "sell value": "sell_value", "nilai jual": "sell_value",
        "net value": "net_value",
    }
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns=col_map)

    if "broker_code" not in df.columns and len(df.columns) > 0:
        df = df.rename(columns={df.columns[0]: "broker_code"})

    if "net_lot" not in df.columns and "buy_lot" in df.columns and "sell_lot" in df.columns:
        df["net_lot"] = df["buy_lot"] - df["sell_lot"]
    if "net_value" not in df.columns and "buy_value" in df.columns and "sell_value" in df.columns:
        df["net_value"] = df["buy_value"] - df["sell_value"]

    for col in ["buy_lot", "sell_lot", "net_lot", "buy_value", "sell_value", "net_value"]:
        if col in df.columns:
            df[col] = (df[col].astype(str)
                       .str.replace(",", "", regex=False)
                       .str.replace("(", "-", regex=False)
                       .str.replace(")", "", regex=False)
                       .str.strip())
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["broker_code"] = df["broker_code"].astype(str).str.upper().str.strip()
    df["category"] = df["broker_code"].apply(_categorize_broker)
    df["ticker"] = ticker
    return df

def fetch_broker_summary_rti(ticker: str, days: int = 30):
    ticker = ticker.upper().replace(".JK", "")
    url = f"https://rtiindonesia.com/market/broker-summary?ticker={ticker}&period={days}"
    
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                df = _parse_rti_html(resp.text, ticker)
                if df is not None and not df.empty:
                    return df
        except:
            pass
        time.sleep(2 * (attempt + 1))
    return None

def _parse_rti_html(html: str, ticker: str):
    try:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        for tbl in tables:
            try:
                df = pd.read_html(StringIO(str(tbl)))[0]
                cols = " ".join([str(c).lower() for c in df.columns])
                if any(k in cols for k in ["broker", "buy", "sell", "net"]):
                    return _normalize_broker_df(df, ticker)
            except:
                continue
        return None
    except:
        return None

def compute_broker_score(df_broker: pd.DataFrame) -> dict:
    if df_broker is None or df_broker.empty:
        return {"score": 0, "signal": "No Data", "detail": [], "smart_net_lot": 0, "retail_net_lot": 0}

    df_smart = df_broker[df_broker["category"] == "smart_money"]
    df_retail = df_broker[df_broker["category"] == "retail"]

    smart_net = float(df_smart["net_lot"].sum()) if "net_lot" in df_smart.columns else 0
    retail_net = float(df_retail["net_lot"].sum()) if "net_lot" in df_retail.columns else 0

    top_buyer_cat = df_broker.nlargest(1, "net_lot")["category"].iloc[0] if not df_broker.empty else "unknown"

    score = 0
    if top_buyer_cat == "smart_money": score += 3
    if smart_net > 0: score += 2
    if retail_net < 0: score += 1
    if smart_net > 0: score += 1
    score = max(0, min(score, 10))

    signal = "🟢 Akumulasi Kuat" if score >= 8 else "🟡 Akumulasi" if score >= 6 else "⚪ Netral" if score >= 4 else "🔴 Distribusi"

    return {
        "score": score,
        "signal": signal,
        "smart_net_lot": smart_net,
        "retail_net_lot": retail_net
    }

def fetch_broker_scores_batch(tickers, days=30, delay=1.7, progress_callback=None):
    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i/total, f"Fetching broker: {ticker} ({i+1}/{total})")
        df = fetch_broker_summary_rti(ticker, days)
        results[ticker] = compute_broker_score(df)
        time.sleep(delay)
    if progress_callback:
        progress_callback(1.0, "Selesai!")
    return results

def style_broker_score(val):
    try:
        num = float(val)
        if num >= 8: return "background-color: #1a6b1a; color: white; font-weight: bold"
        if num >= 6: return "background-color: #4caf50; color: white; font-weight: bold"
        if num >= 4: return "background-color: #f5f5f5; color: #333;"
        return "background-color: #ff9800; color: white;"
    except:
        return ""

def style_broker_signal(val):
    val = str(val)
    if "Akumulasi Kuat" in val: return "color: #1a6b1a; font-weight: bold"
    if "Akumulasi" in val: return "color: #4caf50; font-weight: bold"
    return ""

def render_broker_detail_tab(ticker, result):
    st.markdown(f"### 🏦 Broker Summary: **{ticker}**")
    col1, col2, col3 = st.columns(3)
    col1.metric("Score", f"{result.get('score',0)}/10")
    col2.metric("Signal", result.get('signal', 'No Data'))
    col3.metric("Smart Net Lot", f"{result.get('smart_net_lot',0):+,.0f}")
    st.caption("Detail lengkap akan ditampilkan jika data tersedia.")

# =====================================================
# STREAMLIT APP UTAMA
# =====================================================

st.set_page_config(page_title="Smart Money Monitor v19 + Broker", layout="wide")
st.title("🚀 Dashboard Akumulasi: Smart Money Monitor v19 + Broker Summary")

# Cache Data
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    start = end_date - timedelta(days=120)
    try:
        df = yf.download(all_tickers, start=start, end=end_date, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low'], df['Open']
        return df[['Close']], df[['Volume']], df[['High']], df[['Low']], df[['Open']]
    except:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# Load Emiten
def load_data_auto():
    if os.path.exists('FreeFloat.xlsx'):
        try:
            df = pd.read_excel('FreeFloat.xlsx')
            df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK','')
            return df, 'FreeFloat.xlsx'
        except:
            pass
    return pd.DataFrame({'Kode Saham': ['BBCA','TLKM','ASII'], 'Free Float': [30,45,25]}), "Default"

df_emiten, loaded_file = load_data_auto()

# ===================== SIDEBAR =====================
st.sidebar.header("⚙️ Konfigurasi")

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (kosong = semua)", target_list)

min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=100000)

st.sidebar.markdown("---")
st.sidebar.subheader("🏦 Broker Summary Analysis")
enable_broker = st.sidebar.checkbox("Aktifkan Broker Summary Analysis", value=True)
broker_mode = st.sidebar.radio("Mode Broker", ["🌐 Auto Fetch RTI", "📁 Upload CSV Manual"])
broker_days = st.sidebar.slider("Periode Broker (hari)", 5, 60, 30)
max_broker_stocks = st.sidebar.slider("Maksimal saham untuk Broker Analysis", 30, 200, 100, 10)

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", type="primary", use_container_width=True)

# ===================== MAIN ANALYSIS =====================
if btn_analisa:
    with st.spinner("Menganalisa saham..."):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l, df_o = fetch_yf_all_data(tuple(tickers_jk), date.today())

        # === TEMPAT FUNGSI ANALISA TEKNIKAL ANDA ===
        # Silakan ganti bagian ini dengan fungsi get_signals_and_data() Anda yang asli
        # Untuk sementara saya buat contoh sederhana:
        data = []
        for t in active_list[:200]:   # batasi agar tidak terlalu berat
            data.append({
                'Kode Saham': t,
                'Last Price': 1500,
                'Above MA20': 'YA',
                'Market RS': 'Outperform',
                'Early Momentum Score': np.random.randint(4,10),
                'Silent Score': np.random.randint(3,9),
            })
        df_res = pd.DataFrame(data)

        # ===================== BROKER ANALYSIS =====================
        broker_scores = {}
        if enable_broker and not df_res.empty:
            candidate_tickers = df_res['Kode Saham'].tolist()

            # Batasi jumlah saham
            if len(candidate_tickers) > max_broker_stocks:
                candidate_tickers = candidate_tickers[:max_broker_stocks]

            st.info(f"🔍 Menganalisa Broker Summary untuk **{len(candidate_tickers)} saham**")

            if broker_mode == "🌐 Auto Fetch RTI":
                with st.spinner("Mengambil data dari RTI Business..."):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    def progress_callback(prog, msg):
                        progress_bar.progress(prog)
                        status_text.caption(msg)
                    
                    broker_scores = fetch_broker_scores_batch(
                        candidate_tickers, 
                        days=broker_days, 
                        delay=1.7,
                        progress_callback=progress_callback
                    )
            else:
                broker_scores = {}  # Upload manual nanti bisa ditambahkan

            # Tambah kolom ke dataframe
            df_res["Broker Score"] = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("score", 0))
            df_res["Broker Signal"] = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("signal", "No Data"))
            df_res["Smart Net Lot"] = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("smart_net_lot", 0))

        st.session_state.analisa_hasil = {
            "df_res": df_res,
            "broker_scores": broker_scores
        }

# ===================== TAMPILKAN HASIL =====================
if "analisa_hasil" in st.session_state and st.session_state.analisa_hasil:
    df_res = st.session_state.analisa_hasil["df_res"]
    broker_scores = st.session_state.analisa_hasil.get("broker_scores", {})

    tab1, tab2, tab3, tab_moon = st.tabs([
        "🔥 Shortlist Utama", "🔭 Pre-Breakout", 
        "🕵️ Silent Accumulation", "🌙 Moonstock Radar"
    ])

    with tab_moon:
        st.subheader("🌙 Moonstock Radar — Prioritas Tertinggi")
        if enable_broker and "Broker Score" in df_res.columns:
            df_m = df_res.copy()
            df_m["Moonstock Score"] = (
                (df_m["Broker Score"] >= 6).astype(int) * 2 +
                (df_m.get("Early Momentum Score", 0) >= 6).astype(int) +
                (df_m.get("Silent Score", 0) >= 5).astype(int) +
                (df_m.get("Above MA20", "") == "YA").astype(int) +
                (df_m.get("Market RS", "") == "Outperform").astype(int)
            )

            df_moon = df_m[df_m["Moonstock Score"] >= 4].sort_values("Moonstock Score", ascending=False)

            if not df_moon.empty:
                st.dataframe(
                    df_moon[['Kode Saham', 'Moonstock Score', 'Broker Score', 'Broker Signal', 
                             'Early Momentum Score', 'Silent Score']].style
                    .map(style_broker_score, subset=['Broker Score'])
                    .map(style_broker_signal, subset=['Broker Signal']),
                    use_container_width=True
                )

                st.markdown("### Detail Broker Summary")
                for _, row in df_moon.iterrows():
                    ticker = row['Kode Saham']
                    if ticker in broker_scores:
                        with st.expander(f"🌙 {ticker} — Moonstock Score: {int(row['Moonstock Score'])}/5"):
                            render_broker_detail_tab(ticker, broker_scores[ticker])
            else:
                st.info("Tidak ada saham yang memenuhi kriteria Moonstock saat ini.")
        else:
            st.warning("Aktifkan Broker Analysis di sidebar.")

else:
    st.info("Klik tombol **JALANKAN ANALISA** di sidebar untuk memulai.")

st.caption("Dashboard v19 + Broker Summary | Data diambil dari RTI Business")
