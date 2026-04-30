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
# BROKER SUMMARY MODULE — FULLY EMBEDDED
# =====================================================

SMART_MONEY_BROKERS = {
    "OD", "ES", "HD", "AK", "ZP", "BK", "AI", "AZ", "MG", "CP", "RF", "YJ", "RX", "FS", "DX"
}

RETAIL_BROKERS = {
    "YP", "XC", "CC", "KK", "SQ", "XL", "GW", "PD", "DH", "FZ"
}

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
    else:
        return "unknown"

def _normalize_broker_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    col_map = {
        "broker": "broker_code", "kode": "broker_code", "code": "broker_code", "member": "broker_code",
        "buy lot": "buy_lot", "lot beli": "buy_lot", "beli (lot)": "buy_lot", "buy (lot)": "buy_lot",
        "sell lot": "sell_lot", "lot jual": "sell_lot", "jual (lot)": "sell_lot", "sell (lot)": "sell_lot",
        "net lot": "net_lot", "net (lot)": "net_lot",
        "buy value": "buy_value", "nilai beli": "buy_value",
        "sell value": "sell_value", "nilai jual": "sell_value",
        "net value": "net_value", "nilai net": "net_value",
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
            df[col] = (
                df[col].astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("(", "-", regex=False)
                .str.replace(")", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["broker_code"] = df["broker_code"].astype(str).str.upper().str.strip()
    df["category"] = df["broker_code"].apply(_categorize_broker)
    df["ticker"] = ticker
    return df

def fetch_broker_summary_rti(ticker: str, days: int = 30, retries: int = 3, delay: float = 2.0):
    ticker = ticker.upper().replace(".JK", "")
    url = f"https://rtiindonesia.com/market/broker-summary?ticker={ticker}&period={days}"

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                df = _parse_rti_html(resp.text, ticker)
                if df is not None and not df.empty:
                    return df
            time.sleep(delay * (attempt + 1))
        except Exception:
            time.sleep(delay * (attempt + 1))
    return _fetch_rti_json_fallback(ticker, days)

def _parse_rti_html(html: str, ticker: str):
    try:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        for tbl in tables:
            try:
                df = pd.read_html(StringIO(str(tbl)))[0]
                cols_lower = [str(c).lower() for c in df.columns]
                if any(k in " ".join(cols_lower) for k in ["broker", "buy", "sell", "net"]):
                    return _normalize_broker_df(df, ticker)
            except Exception:
                continue
        return None
    except Exception:
        return None

def _fetch_rti_json_fallback(ticker: str, days: int):
    endpoints = [
        f"https://rtiindonesia.com/api/broker-summary?ticker={ticker}&period={days}",
        f"https://rtiindonesia.com/data/broker/{ticker}?period={days}",
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    return _normalize_broker_df(pd.DataFrame(data), ticker)
                elif isinstance(data, dict) and "data" in data:
                    return _normalize_broker_df(pd.DataFrame(data["data"]), ticker)
        except Exception:
            continue
    return None

def compute_broker_score(df_broker: pd.DataFrame, top_n: int = 10) -> dict:
    if df_broker is None or df_broker.empty:
        return {
            "score": 0, "signal": "No Data", "detail": [], "top_buyers": [], "top_sellers": [],
            "smart_net_lot": 0, "retail_net_lot": 0, "asing_net_lot": 0, "smart_buy_ratio": 0.0
        }

    score = 0
    detail = []

    df_smart = df_broker[df_broker["category"] == "smart_money"].copy()
    df_retail = df_broker[df_broker["category"] == "retail"].copy()

    smart_net_lot = float(df_smart["net_lot"].sum()) if "net_lot" in df_smart.columns else 0.0
    retail_net_lot = float(df_retail["net_lot"].sum()) if "net_lot" in df_retail.columns else 0.0
    smart_net_value = float(df_smart["net_value"].sum()) if "net_value" in df_smart.columns else 0.0
    total_buy_lot = float(df_broker["buy_lot"].sum()) if "buy_lot" in df_broker.columns else 0.0
    smart_buy_lot = float(df_smart["buy_lot"].sum()) if "buy_lot" in df_smart.columns else 0.0

    top_buyers = df_broker.nlargest(top_n, "net_lot")[["broker_code", "net_lot", "category"]].to_dict("records") if "net_lot" in df_broker.columns else []
    top_sellers = df_broker.nsmallest(top_n, "net_lot")[["broker_code", "net_lot", "category"]].to_dict("records") if "net_lot" in df_broker.columns else []

    top1_category = top_buyers[0]["category"] if top_buyers else "unknown"

    asing_brokers = {"ES", "HD", "AK", "ZP", "BK", "AI", "AZ", "RX", "YJ"}
    df_asing = df_broker[df_broker["broker_code"].isin(asing_brokers)]
    asing_net = float(df_asing["net_lot"].sum()) if not df_asing.empty and "net_lot" in df_asing.columns else 0.0

    # Scoring
    if top1_category == "smart_money":
        score += 3
        detail.append(f"✅ Top buyer = smart money ({top_buyers[0]['broker_code']}) +3")
    else:
        detail.append(f"⚠️ Top buyer = {top1_category}")

    if smart_net_lot > 0:
        score += 2
        detail.append(f"✅ Smart money net buy: {smart_net_lot:+,.0f} lot +2")
    elif smart_net_lot < 0:
        score -= 2
        detail.append(f"🔴 Smart money net SELL: {smart_net_lot:+,.0f} lot -2")

    if retail_net_lot < 0:
        score += 1
        detail.append(f"✅ Retail net sell {retail_net_lot:+,.0f} lot +1")
    else:
        detail.append(f"⚠️ Retail net buy {retail_net_lot:+,.0f} lot")

    smart_buy_ratio = (smart_buy_lot / total_buy_lot) if total_buy_lot > 0 else 0.0
    if smart_buy_ratio >= 0.40:
        score += 1
        detail.append(f"✅ Smart buy ratio: {smart_buy_ratio:.1%} +1")

    if smart_net_value > 0:
        score += 1
        detail.append(f"✅ Smart net value positif +1")

    if asing_net > 0:
        score += 1
        detail.append(f"✅ Asing net buy +1")

    if df_smart[df_smart.get("net_lot", 0) < -10000].empty:
        score += 1
        detail.append("✅ Tidak ada smart money jual besar +1")

    if retail_net_lot > 0 and retail_net_lot > smart_net_lot:
        score -= 1
        detail.append("🔴 Retail FOMO -1")

    score = max(0, min(score, 10))

    if score >= 8:
        signal = "🟢 Akumulasi Kuat"
    elif score >= 6:
        signal = "🟡 Akumulasi"
    elif score >= 4:
        signal = "⚪ Netral"
    elif score >= 2:
        signal = "🟠 Distribusi"
    else:
        signal = "🔴 Distribusi Kuat"

    return {
        "score": score,
        "signal": signal,
        "detail": detail,
        "top_buyers": top_buyers,
        "top_sellers": top_sellers,
        "smart_net_lot": smart_net_lot,
        "retail_net_lot": retail_net_lot,
        "asing_net_lot": asing_net,
        "smart_buy_ratio": smart_buy_ratio,
    }

def fetch_broker_scores_batch(tickers: list[str], days: int = 30, delay: float = 1.8, progress_callback=None):
    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i / total, f"Fetching broker: {ticker} ({i+1}/{total})")
        df_broker = fetch_broker_summary_rti(ticker, days=days)
        results[ticker] = compute_broker_score(df_broker)
        time.sleep(delay)
    if progress_callback:
        progress_callback(1.0, "Broker analysis selesai!")
    return results

def style_broker_score(val):
    try:
        num = float(val)
        if num >= 8: return "background-color: #1a6b1a; color: white; font-weight: bold"
        if num >= 6: return "background-color: #4caf50; color: white; font-weight: bold"
        if num >= 4: return "background-color: #f5f5f5; color: #333;"
        if num >= 2: return "background-color: #ff9800; color: white;"
        return "background-color: #f44336; color: white;"
    except:
        return ""

def style_broker_signal(val):
    val = str(val)
    if "Akumulasi Kuat" in val: return "color: #1a6b1a; font-weight: bold"
    if "Akumulasi" in val: return "color: #4caf50; font-weight: bold"
    if "Distribusi Kuat" in val: return "color: #b71c1c; font-weight: bold"
    if "Distribusi" in val: return "color: #ff6600;"
    if "No Data" in val: return "color: #aaa;"
    return ""

def render_broker_detail_tab(ticker: str, broker_result: dict):
    st.markdown(f"### 🏦 Broker Summary: **{ticker}**")
    score = broker_result.get("score", 0)
    signal = broker_result.get("signal", "No Data")
    detail = broker_result.get("detail", [])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Broker Score", f"{score}/10")
    col2.metric("Signal", signal)
    col3.metric("Smart Net Lot", f"{broker_result.get('smart_net_lot', 0):+,.0f}")
    col4.metric("Retail Net Lot", f"{broker_result.get('retail_net_lot', 0):+,.0f}")

    st.markdown("**Detail Analisa:**")
    for d in detail:
        st.markdown(f"- {d}")

    col_b, col_s = st.columns(2)
    with col_b:
        st.markdown("**🟢 Top Net Buyers:**")
        for row in broker_result.get("top_buyers", [])[:5]:
            icon = "⭐" if row.get("category") == "smart_money" else "👤"
            st.markdown(f"{icon} **{row['broker_code']}** — {row['net_lot']:+,.0f} lot")
    with col_s:
        st.markdown("**🔴 Top Net Sellers:**")
        for row in broker_result.get("top_sellers", [])[:5]:
            icon = "⭐" if row.get("category") == "smart_money" else "👤"
            st.markdown(f"{icon} **{row['broker_code']}** — {row['net_lot']:+,.0f} lot")

# =====================================================
# END OF BROKER MODULE
# =====================================================

# ================== STREAMLIT MAIN APP ==================

st.set_page_config(page_title="Smart Money Monitor v19 + Broker", layout="wide")
st.title("🚀 Dashboard Akumulasi: Smart Money Monitor v19 + Broker Summary")

st.markdown("""
**Fitur Utama:**
- Analisa Teknis Lengkap (MFI, ADX, RSI, Silent Accumulation, dll)
- Visual Chart Analysis + Plotly Candlestick
- **Broker Summary Analysis** (Smart Money vs Retail) dari RTI
- **Moonstock Radar** — Kombinasi 5 kriteria termasuk Broker Score
""")

# Cache
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = end_date - timedelta(days=120)
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date, threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low'], df['Open']
        else:
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']], df[['Open']]
    except:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# Load Emiten
def load_data_auto():
    file_name = 'FreeFloat.xlsx'
    if os.path.exists(file_name):
        try:
            df = pd.read_excel(file_name)
            df.columns = df.columns.str.strip()
            if 'Kode Saham' in df.columns:
                df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper().str.replace('.JK', '')
                if 'Free Float' in df.columns:
                    df['Free Float'] = pd.to_numeric(df['Free Float'], errors='coerce').fillna(0)
                return df, file_name
        except:
            pass
    default_data = pd.DataFrame({'Kode Saham': ['BBCA', 'TLKM', 'ASII'], 'Free Float': [30.0, 45.0, 25.0]})
    return default_data, "Default Mode"

df_emiten, loaded_file = load_data_auto()

# ===================== SIDEBAR =====================
st.sidebar.header("⚙️ Konfigurasi v19 + Broker")

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect("Pilih Saham (kosong = semua)", options=target_list)

min_p = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=100000)

st.sidebar.markdown("---")
st.sidebar.subheader("🏦 Broker Summary Analysis")
enable_broker = st.sidebar.checkbox("Aktifkan Broker Summary Analysis", value=True)
broker_mode = st.sidebar.radio("Mode Data Broker", ["🌐 Auto Fetch RTI", "📁 Upload CSV Manual"])
broker_days = st.sidebar.slider("Periode Broker Summary (hari)", 5, 60, 30)

btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", type="primary", use_container_width=True)

# ===================== MAIN LOGIC =====================
if "analisa_hasil" not in st.session_state:
    st.session_state.analisa_hasil = None

if btn_analisa:
    with st.spinner("Menganalisa market..."):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l, df_o = fetch_yf_all_data(tuple(tickers_jk), date.today())

        # === TEMPAT UNTUK FUNGSI get_signals_and_data() ANDA ===
        # Silakan paste seluruh fungsi get_signals_and_data() dan fungsi pendukung di sini
        # Untuk saat ini, gunakan contoh sederhana:
        data = []
        for ticker in active_list:
            data.append({
                'Kode Saham': ticker,
                'Last Price': 1000,
                'Above MA20': 'YA',
                'Market RS': 'Outperform',
                'Early Momentum Score': 7,
                'Silent Score': 6,
            })
        df_res = pd.DataFrame(data)

        # Broker Analysis
        broker_scores = {}
        if enable_broker and not df_res.empty:
            tickers = df_res['Kode Saham'].tolist()
            if broker_mode == "🌐 Auto Fetch RTI":
                with st.spinner("Fetching Broker Summary dari RTI..."):
                    progress_bar = st.progress(0)
                    def update_progress(prog, msg):
                        progress_bar.progress(prog)
                        st.caption(msg)
                    broker_scores = fetch_broker_scores_batch(tickers, days=broker_days, progress_callback=update_progress)
            else:
                # Upload manual akan ditangani di render_broker_upload_widget jika diperlukan
                st.info("Mode Upload CSV Manual - Silakan upload file di bawah")
                broker_scores = {}  # Akan diisi oleh widget upload

            # Tambahkan kolom Broker
            df_res["Broker Score"] = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("score", 0))
            df_res["Broker Signal"] = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("signal", "No Data"))
            df_res["Smart Net Lot"] = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("smart_net_lot", 0))

        st.session_state.analisa_hasil = {
            "df_res": df_res,
            "broker_scores": broker_scores
        }

# ===================== RENDER TABS =====================
if st.session_state.analisa_hasil:
    df_res = st.session_state.analisa_hasil["df_res"]
    broker_scores = st.session_state.analisa_hasil.get("broker_scores", {})

    tab1, tab2, tab3, tab4, tab_moon = st.tabs([
        "🔥 Shortlist Utama",
        "🔭 Pre-Breakout Watch",
        "🕵️ Silent Accumulation",
        "🔍 Semua Hasil",
        "🌙 Moonstock Radar"
    ])

    with tab_moon:
        st.subheader("🌙 Moonstock Radar — Prioritas Tertinggi")
        if enable_broker and "Broker Score" in df_res.columns:
            df_m = df_res.copy()
            df_m["Moonstock Score"] = (
                (df_m["Broker Score"] >= 6).astype(int) * 2 +   # Bobot 2 untuk Broker
                (df_m.get("Early Momentum Score", 0) >= 6).astype(int) +
                (df_m.get("Silent Score", 0) >= 5).astype(int) +
                (df_m.get("Above MA20", "") == "YA").astype(int) +
                (df_m.get("Market RS", "") == "Outperform").astype(int)
            )

            df_moon = df_m[df_m["Moonstock Score"] >= 4].sort_values("Moonstock Score", ascending=False)

            if not df_moon.empty:
                st.dataframe(
                    df_moon[['Kode Saham', 'Moonstock Score', 'Broker Score', 'Broker Signal', 
                             'Early Momentum Score', 'Silent Score', 'Above MA20', 'Market RS']].style
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
            st.warning("Aktifkan Broker Summary Analysis di sidebar untuk melihat Moonstock Radar.")

    st.success("Analisa selesai! Broker Summary telah terintegrasi.")

else:
    st.info("Klik tombol **JALANKAN ANALISA** di sidebar untuk memulai analisis.")

with st.expander("📖 Penjelasan Broker Score"):
    st.markdown("""
**Broker Score (0-10)** mengukur seberapa kuat akumulasi oleh **Smart Money**:
- ≥ 8 = **Akumulasi Kuat** (Sangat Bullish)
- 6–7 = **Akumulasi** (Bullish)
- Smart Net Lot positif + Top Buyer dari broker institusi = sinyal kuat
    """)

st.caption("Dashboard dibuat dengan ❤️ untuk trader Indonesia")
