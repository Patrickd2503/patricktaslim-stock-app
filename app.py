import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO
import pandas_ta as pta
import requests
import base64
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────
# BROKER SUMMARY MODULE — EMBEDDED (v20)
# Sumber: broker_summary_module.py (Remora Trader Screener)
# ─────────────────────────────────────────────
import time
from io import StringIO
try:
    from bs4 import BeautifulSoup
    _BS4_OK = True
except ImportError:
    _BS4_OK = False

BROKER_MODULE_AVAILABLE = True  # always available (embedded)

# ── Klasifikasi Broker (Remora Day 3, 4, 5) ──
SMART_MONEY_BROKERS = {
    "OD", "ES", "HD", "AK", "ZP", "BK", "AI", "AZ",
    "MG", "CP", "RF", "YJ", "RX", "FS", "DX",
}
RETAIL_BROKERS = {
    "YP", "XC", "CC", "KK", "SQ", "XL", "GW", "PD", "DH", "FZ",
}

_BROKER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Referer": "https://rtiindonesia.com/",
}


def _categorize_broker(code: str) -> str:
    if code in SMART_MONEY_BROKERS: return "smart_money"
    if code in RETAIL_BROKERS:      return "retail"
    return "unknown"


def _normalize_broker_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    col_map = {
        "broker": "broker_code", "kode": "broker_code", "code": "broker_code", "member": "broker_code",
        "buy lot": "buy_lot", "lot beli": "buy_lot", "beli (lot)": "buy_lot",
        "buy (lot)": "buy_lot", "volume buy": "buy_lot",
        "sell lot": "sell_lot", "lot jual": "sell_lot", "jual (lot)": "sell_lot",
        "sell (lot)": "sell_lot", "volume sell": "sell_lot",
        "net lot": "net_lot", "net (lot)": "net_lot",
        "buy value": "buy_value", "nilai beli": "buy_value", "value buy": "buy_value",
        "sell value": "sell_value", "nilai jual": "sell_value", "value sell": "sell_value",
        "net value": "net_value", "nilai net": "net_value",
    }
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns=col_map)
    if "broker_code" not in df.columns:
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


def fetch_broker_summary_rti(ticker: str, days: int = 30) -> pd.DataFrame | None:
    ticker = ticker.upper().replace(".JK", "")
    url = f"https://rtiindonesia.com/market/broker-summary?ticker={ticker}&period={days}"
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_BROKER_HEADERS, timeout=15)
            if resp.status_code == 200 and _BS4_OK:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tbl in soup.find_all("table"):
                    try:
                        df = pd.read_html(StringIO(str(tbl)))[0]
                        cols_lower = [str(c).lower() for c in df.columns]
                        if any(k in " ".join(cols_lower) for k in ["broker", "buy", "sell", "net"]):
                            return _normalize_broker_df(df, ticker)
                    except Exception:
                        continue
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    # Fallback JSON endpoints
    for url_j in [
        f"https://rtiindonesia.com/api/broker-summary?ticker={ticker}&period={days}",
        f"https://rtiindonesia.com/data/broker/{ticker}?period={days}",
    ]:
        try:
            resp = requests.get(url_j, headers=_BROKER_HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("data", [])
                if rows:
                    return _normalize_broker_df(pd.DataFrame(rows), ticker)
        except Exception:
            continue
    return None


def compute_broker_score(df_broker: pd.DataFrame, top_n: int = 10) -> dict:
    empty = {
        "score": 0, "signal": "No Data", "detail": [],
        "top_buyers": [], "top_sellers": [],
        "smart_net_lot": 0, "retail_net_lot": 0,
        "asing_net_lot": 0, "smart_buy_ratio": 0.0,
    }
    if df_broker is None or df_broker.empty:
        return empty

    score = 0
    detail = []
    df_smart  = df_broker[df_broker["category"] == "smart_money"].copy()
    df_retail = df_broker[df_broker["category"] == "retail"].copy()

    smart_net_lot   = float(df_smart["net_lot"].sum())   if "net_lot"   in df_smart.columns   else 0.0
    retail_net_lot  = float(df_retail["net_lot"].sum())  if "net_lot"   in df_retail.columns  else 0.0
    smart_net_value = float(df_smart["net_value"].sum()) if "net_value" in df_smart.columns   else 0.0
    total_buy_lot   = float(df_broker["buy_lot"].sum())  if "buy_lot"   in df_broker.columns  else 0.0
    smart_buy_lot   = float(df_smart["buy_lot"].sum())   if "buy_lot"   in df_smart.columns   else 0.0

    if "net_lot" in df_broker.columns:
        top_buyers  = df_broker.nlargest(top_n,  "net_lot")[["broker_code", "net_lot", "category"]].to_dict("records")
        top_sellers = df_broker.nsmallest(top_n, "net_lot")[["broker_code", "net_lot", "category"]].to_dict("records")
    else:
        top_buyers = top_sellers = []

    top1_cat = top_buyers[0]["category"] if top_buyers else "unknown"
    asing_brokers = {"ES", "HD", "AK", "ZP", "BK", "AI", "AZ", "RX", "YJ"}
    df_asing  = df_broker[df_broker["broker_code"].isin(asing_brokers)]
    asing_net = float(df_asing["net_lot"].sum()) if not df_asing.empty and "net_lot" in df_asing.columns else 0.0

    if top1_cat == "smart_money":
        score += 3
        detail.append(f"✅ Top buyer = smart money ({top_buyers[0]['broker_code']}) +3")
    else:
        detail.append(f"⚠️ Top buyer = {top1_cat} ({top_buyers[0]['broker_code'] if top_buyers else '-'})")

    if smart_net_lot > 0:
        score += 2
        detail.append(f"✅ Smart money net buy: {smart_net_lot:+,.0f} lot +2")
    elif smart_net_lot < 0:
        score -= 2
        detail.append(f"🔴 Smart money net SELL: {smart_net_lot:+,.0f} lot -2 (BAHAYA)")

    if retail_net_lot < 0:
        score += 1
        detail.append(f"✅ Retail net sell {retail_net_lot:+,.0f} lot → barang ke smart money +1")
    else:
        detail.append(f"⚠️ Retail net buy {retail_net_lot:+,.0f} lot")

    smart_buy_ratio = (smart_buy_lot / total_buy_lot) if total_buy_lot > 0 else 0.0
    if smart_buy_ratio >= 0.40:
        score += 1
        detail.append(f"✅ Smart money buy ratio: {smart_buy_ratio:.1%} +1")

    if smart_net_value > 0:
        score += 1
        detail.append(f"✅ Smart money net value positif (Rp {smart_net_value/1e9:.1f}B) +1")

    if asing_net > 0:
        score += 1
        detail.append(f"✅ Asing net buy: {asing_net:+,.0f} lot +1")
    elif asing_net < 0:
        detail.append(f"⚠️ Asing net sell: {asing_net:+,.0f} lot")

    smart_sellers = df_smart[df_smart["net_lot"] < -10000] if "net_lot" in df_smart.columns else pd.DataFrame()
    if smart_sellers.empty:
        score += 1
        detail.append("✅ Tidak ada smart money distribusi besar +1")
    else:
        detail.append(f"⚠️ Ada smart money jual besar: {list(smart_sellers['broker_code'])}")

    if retail_net_lot > 0 and retail_net_lot > smart_net_lot:
        score -= 1
        detail.append("🔴 Retail net buy > smart money → FOMO retail -1")

    score = max(0, min(score, 10))

    if   score >= 8: signal = "🟢 Akumulasi Kuat"
    elif score >= 6: signal = "🟡 Akumulasi"
    elif score >= 4: signal = "⚪ Netral"
    elif score >= 2: signal = "🟠 Distribusi"
    else:            signal = "🔴 Distribusi Kuat"

    return {
        "score": score, "signal": signal, "detail": detail,
        "top_buyers": top_buyers, "top_sellers": top_sellers,
        "smart_net_lot": smart_net_lot, "retail_net_lot": retail_net_lot,
        "asing_net_lot": asing_net, "smart_buy_ratio": smart_buy_ratio,
    }


def fetch_broker_scores_batch(tickers: list, days: int = 30, delay: float = 1.5,
                               progress_callback=None) -> dict:
    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i / total, f"Fetching broker data: {ticker} ({i+1}/{total})")
        df_b = fetch_broker_summary_rti(ticker, days=days)
        if df_b is not None and not df_b.empty:
            results[ticker] = compute_broker_score(df_b)
        else:
            results[ticker] = {
                "score": 0, "signal": "No Data",
                "detail": ["❌ Data tidak tersedia dari RTI"],
                "top_buyers": [], "top_sellers": [],
                "smart_net_lot": 0, "retail_net_lot": 0,
                "asing_net_lot": 0, "smart_buy_ratio": 0.0,
            }
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
        if num >= 2: return "background-color: #ff9800; color: white;"
        if num > 0:  return "background-color: #f44336; color: white; font-weight: bold"
    except Exception:
        pass
    return ""


def style_broker_signal(val):
    val = str(val)
    if "Akumulasi Kuat"   in val: return "color: #1a6b1a; font-weight: bold"
    if "Akumulasi"        in val: return "color: #4caf50; font-weight: bold"
    if "Distribusi Kuat"  in val: return "color: #b71c1c; font-weight: bold"
    if "Distribusi"       in val: return "color: #ff6600;"
    if "No Data"          in val: return "color: #aaa;"
    return ""


def render_broker_detail_tab(ticker: str, broker_result: dict):
    st.markdown(f"### 🏦 Broker Summary: **{ticker}**")
    score  = broker_result.get("score", 0)
    signal = broker_result.get("signal", "No Data")
    detail = broker_result.get("detail", [])
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Broker Score",     f"{score}/10")
    col2.metric("Signal",           signal)
    col3.metric("Smart Net (Lot)",  f"{broker_result.get('smart_net_lot', 0):+,.0f}")
    col4.metric("Retail Net (Lot)", f"{broker_result.get('retail_net_lot', 0):+,.0f}")
    st.markdown("**Detail Analisa:**")
    for d in detail:
        st.markdown(f"- {d}")
    col_b, col_s = st.columns(2)
    with col_b:
        st.markdown("**🟢 Top Net Buyers:**")
        for row in broker_result.get("top_buyers", [])[:5]:
            icon = "⭐" if row["category"] == "smart_money" else "👤"
            st.markdown(f"{icon} **{row['broker_code']}** — {row['net_lot']:+,.0f} lot")
    with col_s:
        st.markdown("**🔴 Top Net Sellers:**")
        for row in broker_result.get("top_sellers", [])[:5]:
            icon = "⭐" if row["category"] == "smart_money" else "👤"
            st.markdown(f"{icon} **{row['broker_code']}** — {row['net_lot']:+,.0f} lot")


def render_broker_upload_widget() -> dict:
    st.markdown("#### 📁 Upload Broker Summary CSV")
    st.caption(
        "Download dari RTI Business / IDX → lalu upload di sini. "
        "Format nama file: `KODE_broker.csv` (contoh: `BBCA_broker.csv`)"
    )
    uploaded_files = st.file_uploader(
        "Upload file CSV broker summary",
        type=["csv"],
        accept_multiple_files=True,
        key="broker_csv_upload",
    )
    results = {}
    if uploaded_files:
        for f in uploaded_files:
            name   = f.name.replace("_broker", "").replace(".csv", "").upper()
            ticker = name.split("_")[0]
            try:
                df_b   = pd.read_csv(f, thousands=",", encoding="utf-8-sig")
                df_b   = _normalize_broker_df(df_b, ticker)
                result = compute_broker_score(df_b)
                results[ticker] = result
                st.success(f"✅ {ticker}: {result['signal']} (Score {result['score']}/10)")
            except Exception as e:
                st.error(f"❌ Gagal parse {f.name}: {e}")
    return results

# ─────────────────────────────────────────────
# SETUP (jalankan sekali sebelum app pertama kali):
#   pip install playwright
#   playwright install chromium
# ─────────────────────────────────────────────

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI v20", layout="wide")
st.title("🚀 Dashboard Akumulasi: Smart Money Monitor v20 – Broker Summary Analysis")

st.markdown("""
**Update v20:**
- ✅ Semua fitur v19 dipertahankan (Visual Chart Analysis, Plotly Candlestick, Silent Accumulation Radar, AI Chart Analysis)
- 🆕 **Broker Summary Analysis** — Analisa aliran dana berdasarkan data broker RTI Business:
  - Smart Money vs Retail broker tracking (klasifikasi broker Remora Day 3, 4, 5)
  - Broker Score 0–10: Net buy smart money, rasio asing, distribusi broker
  - Signal: Akumulasi Kuat / Akumulasi / Netral / Distribusi / Distribusi Kuat
  - Tab baru **🌙 Moonstock Radar** — gabungan 5 kriteria: Broker + Early Momentum + Silent + MA20 + Market RS
  - Mode data: Auto Fetch RTI Business atau Upload CSV Manual
""")

# ─────────────────────────────────────────────
# 1. CACHE DATA
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    extended_start = end_date - timedelta(days=120)
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date,
                         threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low'], df['Open']
        else:
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']], df[['Open']]
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ─────────────────────────────────────────────
# 2. LOAD DATABASE EMITEN
# ─────────────────────────────────────────────
def load_data_auto():
    file_name = 'FreeFloat.xlsx'
    if os.path.exists(file_name):
        try:
            df = pd.read_excel(file_name)
            df.columns = df.columns.str.strip()
            if 'Kode Saham' in df.columns:
                df['Kode Saham'] = (df['Kode Saham'].astype(str).str.strip()
                                    .str.upper().str.replace('.JK', '', regex=False))
                if 'Free Float' in df.columns:
                    df['Free Float'] = pd.to_numeric(df['Free Float'], errors='coerce').fillna(0)
                    if df['Free Float'].max() <= 1.0 and df['Free Float'].max() > 0:
                        df['Free Float'] = df['Free Float'] * 100
                else:
                    df['Free Float'] = 0
                return df, file_name
        except Exception as e:
            st.error(f"Gagal membaca file {file_name}: {e}")

    default_data = pd.DataFrame({
        'Kode Saham': ['WINS', 'CNKO', 'KOIN'],
        'Free Float': [30.0, 45.0, 20.0]
    })
    return default_data, "Default Mode"

df_emiten, loaded_file = load_data_auto()

# ─────────────────────────────────────────────
# 3. FUNGSI STYLING
# ─────────────────────────────────────────────
def style_mfi(val):
    try:
        num = float(val)
        if num >= 80: return 'background-color: #ff4b4b; color: white'
        if num <= 40: return 'background-color: #008000; color: white'
    except:
        pass
    return ''

def style_market_rs(val):
    if val == 'Outperform': return 'color: #006400; font-weight: bold;'
    return 'color: #ff4b4b;'

def style_pva(val):
    if val == 'Strong Bullish Vol': return 'background-color: rgba(0, 200, 0, 0.3); font-weight: bold'
    if val == 'Bullish Vol':        return 'background-color: rgba(0, 255, 0, 0.2);'
    if val == 'Bearish Vol':        return 'background-color: rgba(255, 0, 0, 0.2);'
    return ''

def style_ma_filter(val):
    if val == 'YA': return 'color: green; font-weight: bold;'
    return 'color: red;'

def style_rel_vol(val):
    try:
        num = float(val)
        if num >= 2.0: return 'background-color: #00cc00; color: white; font-weight: bold'
        if num >= 1.5: return 'background-color: #66ff66;'
    except:
        pass
    return ''

def style_adx(val):
    try:
        num = float(val)
        if num >= 25: return 'background-color: #0066ff; color: white'
    except:
        pass
    return ''

def style_divergence(val):
    if val and 'Bearish' in str(val):
        return 'background-color: #ff9999; color: darkred; font-weight: bold'
    return ''

def style_adx_trend(val):
    if val == 'Rising': return 'color: #006400; font-weight: bold;'
    if val == 'Falling': return 'color: #cc0000;'
    return 'color: gray;'

def style_adx_dir(val):
    if val == 'Bullish (DI+>DI-)': return 'color: #006400; font-weight: bold;'
    if val == 'Bearish (DI->DI+)': return 'color: #cc0000; font-weight: bold;'
    return ''

def style_chart_analysis(val):
    val = str(val)
    if 'Overextended' in val:
        return 'background-color: #ff4b4b; color: white; font-weight: bold'
    if 'Breakout Valid' in val:
        return 'background-color: #1a8c1a; color: white; font-weight: bold'
    if 'Pullback Healthy' in val:
        return 'background-color: #2196F3; color: white; font-weight: bold'
    if 'Uptrend Normal' in val:
        return 'background-color: rgba(0,200,0,0.2); color: #004d00;'
    if 'Downtrend' in val:
        return 'background-color: #ffcccc; color: darkred; font-weight: bold'
    if 'Sideways' in val:
        return 'background-color: #f5f5f5; color: #555;'
    return ''

def style_early_momentum(val):
    """Styling untuk Early Momentum Score (Opsi C)"""
    try:
        num = float(val)
        if num >= 8:  return 'background-color: #ff6600; color: white; font-weight: bold'
        if num >= 6:  return 'background-color: #ffaa00; color: white; font-weight: bold'
        if num >= 4:  return 'background-color: #ffd966; color: #333;'
    except:
        pass
    return ''

def style_prebreakout(val):
    """Styling untuk Pre-Breakout Watch tag"""
    if val == '🔭 Watch':
        return 'background-color: #7b2d8b; color: white; font-weight: bold'
    return ''

def style_silent_score(val):
    """Styling untuk Silent Accumulation Score"""
    try:
        num = float(val)
        if num >= 8:  return 'background-color: #c0392b; color: white; font-weight: bold'
        if num >= 6:  return 'background-color: #e67e22; color: white; font-weight: bold'
        if num >= 4:  return 'background-color: #f39c12; color: #333; font-weight: bold'
    except:
        pass
    return ''

def style_bb_squeeze(val):
    if val == 'SQUEEZE 🔥': return 'background-color: #6c3483; color: white; font-weight: bold'
    if val == 'Sempit':     return 'background-color: #a569bd; color: white;'
    return ''

def style_obv_trend(val):
    if val == 'Rising ↑': return 'color: #1a8c1a; font-weight: bold;'
    if val == 'Falling ↓': return 'color: #cc0000;'
    return 'color: gray;'

# ─────────────────────────────────────────────
# 3b. TRADINGVIEW WIDGET
# ─────────────────────────────────────────────
def show_tradingview_widget(ticker_code: str):
    """
    Menampilkan TradingView Advanced Chart Widget untuk saham BEI.
    ticker_code: kode saham tanpa .JK, misal 'BBCA'
    """
    tv_symbol = f"IDX:{ticker_code}"
    widget_html = f"""
    <div style="border:1px solid #e0e0e0; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,0.10);">
      <div class="tradingview-widget-container" style="height:500px; width:100%;">
        <div id="tradingview_{ticker_code}" style="height:100%; width:100%;"></div>
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
          "container_id": "tradingview_{ticker_code}",
          "studies": [
            "MASimple@tv-basicstudies",
            "RSI@tv-basicstudies",
            "MFI@tv-basicstudies",
            "ADX@tv-basicstudies"
          ],
          "show_popup_button": true,
          "popup_width": "1000",
          "popup_height": "650"
        }});
        </script>
      </div>
    </div>
    <p style="font-size:11px; color:#888; margin-top:4px; text-align:right;">
      Powered by <a href="https://www.tradingview.com/" target="_blank">TradingView</a>
    </p>
    """
    components.html(widget_html, height=540, scrolling=False)


# ─────────────────────────────────────────────
# 4. EXPORT EXCEL
# ─────────────────────────────────────────────
def to_excel_report(df_short, df_watch, df_all):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_short.to_excel(writer, index=False, sheet_name='Shortlist')
        if not df_watch.empty:
            df_watch.to_excel(writer, index=False, sheet_name='Pre-Breakout Watch')
        df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
    return output.getvalue()

# ─────────────────────────────────────────────
# 5. FUNGSI BEARISH DIVERGENCE DETECTION
# ─────────────────────────────────────────────
def detect_bearish_divergence(close: pd.Series, mfi_series: pd.Series, window: int = 10) -> bool:
    if len(close) < window + 1 or len(mfi_series) < window + 1:
        return False

    c_window = close.iloc[-window:]
    m_window = mfi_series.iloc[-window:]

    c_max_idx = c_window.idxmax()
    c_prev = c_window[c_window.index < c_max_idx]
    if c_prev.empty:
        return False
    c_prev_max = c_prev.max()

    price_hh = c_window[c_max_idx] > c_prev_max

    m_at_c_max = m_window.loc[c_max_idx] if c_max_idx in m_window.index else m_window.iloc[-1]
    m_prev_idx = c_prev.idxmax()
    m_at_prev = m_window.loc[m_prev_idx] if m_prev_idx in m_window.index else m_window.iloc[0]

    mfi_lh = m_at_c_max < m_at_prev

    return price_hh and mfi_lh

# ─────────────────────────────────────────────
# 5b. FUNGSI CHART ANALYSIS
# ─────────────────────────────────────────────
def get_chart_analysis(
    close: pd.Series,
    ma20: float,
    last_rsi: float,
    last_adx: float,
    is_adx_bullish: bool,
    is_breakout: str,
    dist_20high: float,
    mfi_change_5d: float,
    p_change_today: float,
    rel_vol: float,
) -> str:
    last_price = float(close.iloc[-1])
    dist_to_ma20_pct = ((last_price - ma20) / ma20 * 100) if ma20 > 0 else 0.0

    if dist_to_ma20_pct > 10 and last_rsi > 70:
        return "Overextended 🚨"

    if last_price < ma20 and not is_adx_bullish and last_adx > 20:
        return "Downtrend ❌"

    if (is_breakout == "YA"
            and rel_vol >= 1.5
            and is_adx_bullish
            and dist_to_ma20_pct <= 10
            and p_change_today > 0):
        return "Breakout Valid 🚀"

    if (last_price >= ma20
            and 0 <= dist_to_ma20_pct <= 5
            and is_adx_bullish
            and mfi_change_5d > 0):
        return "Pullback Healthy 👍"

    if last_price > ma20 and is_adx_bullish and dist_to_ma20_pct <= 10:
        return "Uptrend Normal"

    return "Sideways / Konsolidasi"

# ─────────────────────────────────────────────
# 5c. OPSI C: EARLY MOMENTUM SCORE
# ─────────────────────────────────────────────
def compute_early_momentum_score(
    mfi_change_5d: float,
    adx_trend: str,
    is_above_ma20: str,
    is_adx_bullish: bool,
    rs: str,
    last_rsi: float,
    free_float: float,
    has_bearish_div: bool,
) -> int:
    """
    Skor 0–10 berdasarkan sinyal awal momentum (sebelum breakout/volume meledak).
    Terinspirasi dari pola MDIA: MFI Change tinggi + ADX Rising + Above MA20.

    Komponen:
      +3  MFI Change 5D >= 30 (uang deras masuk)
      +2  MFI Change 5D >= 15 (uang masuk sedang)  [kumulatif dengan atas: maks 3]
      +2  ADX Trend = Rising (momentum baru tumbuh)
      +2  Above MA20 = YA (struktur bullish)
      +1  ADX Direction Bullish (DI+ > DI-)
      +1  Market RS = Outperform
      +1  RSI 45–70 (zona sehat, belum overbought)
      +1  Free Float < 15% (float kecil = explosive move)
      -2  Bearish Divergence terdeteksi
    """
    score = 0

    if mfi_change_5d >= 30:
        score += 3
    elif mfi_change_5d >= 15:
        score += 2

    if adx_trend == "Rising":
        score += 2

    if is_above_ma20 == "YA":
        score += 2

    if is_adx_bullish:
        score += 1

    if rs == "Outperform":
        score += 1

    if 45 <= last_rsi <= 70:
        score += 1

    if 0 < free_float < 15:
        score += 1

    if has_bearish_div:
        score -= 2

    return max(0, min(score, 10))

# ─────────────────────────────────────────────
# 5d. OPSI A: PRE-BREAKOUT WATCH LIST LOGIC
# ─────────────────────────────────────────────
def is_prebreakout_candidate(
    mfi_change_5d: float,
    adx_trend: str,
    is_above_ma20: str,
    is_adx_bullish: bool,
    rs: str,
    consecutive_up: int,
    is_breakout: str,
    rel_vol_20: float,
    has_bearish_div: bool,
    min_mfi_change_watch: float,
    early_score: int,
    min_early_score: int,
) -> bool:
    """
    Opsi A: tangkap saham yang BELUM memenuhi shortlist utama,
    tapi sudah menunjukkan sinyal akumulasi awal.

    Syarat WAJIB:
      - MFI Change 5D >= threshold (uang sudah masuk)
      - ADX Trend = Rising (momentum baru tumbuh)
      - Above MA20 (tidak di downtrend)
      - ADX Bullish (DI+ > DI-)
      - Early Momentum Score >= threshold
      - Tidak ada Bearish Divergence

    Sengaja TIDAK mensyaratkan:
      - Consec Up Days (memang belum naik berturut-turut)
      - 20D Breakout (memang belum breakout)
      - Rel Vol tinggi (volume belum meledak)
      - Market RS (opsional, dikontrol sidebar)
    """
    if has_bearish_div:
        return False
    if mfi_change_5d < min_mfi_change_watch:
        return False
    if adx_trend != "Rising":
        return False
    if is_above_ma20 != "YA":
        return False
    if not is_adx_bullish:
        return False
    if early_score < min_early_score:
        return False
    # Pastikan belum terlambat (belum breakout / belum consec up banyak)
    # Kalau sudah 20D breakout + consec up ≥ 3 → sudah masuk shortlist utama
    if is_breakout == "YA" and consecutive_up >= 3:
        return False
    return True

# ─────────────────────────────────────────────
# 5e. SILENT ACCUMULATION DETECTOR (v18)
# ─────────────────────────────────────────────
def detect_bb_squeeze(close: pd.Series, window: int = 20, squeeze_pct: float = 0.06) -> tuple:
    """
    Deteksi Bollinger Band Squeeze.
    Returns: (squeeze_label, bb_width_pct)
    - 'SQUEEZE 🔥' jika BB sangat sempit (< squeeze_pct dari harga)
    - 'Sempit'     jika BB sempit tapi belum extreme
    - 'Normal'     sisanya
    """
    if len(close) < window + 5:
        return "Normal", 0.0
    ma   = close.rolling(window).mean()
    std  = close.rolling(window).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    bb_width = (upper - lower) / ma  # normalized width

    current_width = float(bb_width.iloc[-1]) if not bb_width.empty else 1.0
    # Bandingkan dengan lebar 50 hari terakhir → apakah sekarang termasuk yang tersempit?
    hist_width = bb_width.dropna().tail(50)
    pct_rank   = (hist_width <= current_width).mean()  # 0–1: semakin kecil = semakin sempit

    if pct_rank <= 0.10:       # 10% tersempit dalam 50 hari
        return "SQUEEZE 🔥", round(current_width * 100, 2)
    elif pct_rank <= 0.25:
        return "Sempit", round(current_width * 100, 2)
    else:
        return "Normal", round(current_width * 100, 2)


def compute_obv_trend(close: pd.Series, volume: pd.Series, lookback: int = 10) -> str:
    """Hitung tren OBV (On-Balance Volume) dalam N hari terakhir."""
    if len(close) < lookback + 2 or len(volume) < lookback + 2:
        return "Flat"
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * volume).cumsum()
    obv_tail = obv.tail(lookback)
    # Regresi linear sederhana: slope positif = OBV naik
    x = range(len(obv_tail))
    slope = np.polyfit(x, obv_tail.values, 1)[0]
    if slope > 0:
        return "Rising ↑"
    elif slope < 0:
        return "Falling ↓"
    return "Flat"


def compute_price_tightness(close: pd.Series, lookback: int = 10) -> float:
    """
    Ukur seberapa 'ketat' pergerakan harga dalam N hari terakhir.
    Returns: koefisien variasi (CV) dalam %. Semakin kecil = harga makin sideways/ketat.
    """
    if len(close) < lookback:
        return 100.0
    tail = close.tail(lookback)
    cv = (tail.std() / tail.mean() * 100) if tail.mean() > 0 else 100.0
    return round(float(cv), 2)


def compute_vol_trend_ratio(volume: pd.Series, short: int = 5, long: int = 20) -> float:
    """
    Rasio rata-rata volume jangka pendek vs jangka panjang.
    > 1.0 = volume mulai naik. Ini menangkap kenaikan volume diam-diam.
    """
    if len(volume) < long:
        return 1.0
    avg_short = float(volume.tail(short).mean())
    avg_long  = float(volume.tail(long).mean())
    return round(avg_short / avg_long, 2) if avg_long > 0 else 1.0


def compute_silent_score(
    bb_squeeze: str,
    obv_trend: str,
    vol_trend_ratio: float,
    price_tightness: float,
    mfi_change_5d: float,
    adx_trend: str,
    is_adx_bullish: bool,
    free_float: float,
    has_bearish_div: bool,
    last_rsi: float,
    is_above_ma20: str,
) -> int:
    """
    Skor 0–10 untuk mendeteksi akumulasi diam-diam (pola KOTA).

    Komponen:
      +3  BB Squeeze (harga terkompresi, siap meledak)
      +1  BB Sempit (tidak sampai squeeze, tapi menyempit)
      +2  OBV Rising (volume masuk diam-diam, konfirmasi akumulasi)
      +2  Vol Trend Ratio >= 1.3 (volume 5D mulai > rata-rata 20D)
      +1  Vol Trend Ratio >= 1.1 (kenaikan volume tipis)  [kumulatif maks 2]
      +1  Price Tightness < 3% (harga sideways ketat = akumulasi)
      +1  MFI Change 5D > 0 (uang mulai masuk walau kecil)
      +1  ADX Trend Rising (momentum mulai)
      +1  ADX Bullish (DI+ > DI-)
      +1  Free Float < 15% (potensi explosive)
      -2  Bearish Divergence
      -1  RSI > 70 (sudah overbought, terlambat)
      -1  Above MA20 = TIDAK (di bawah MA20)
    """
    score = 0

    if bb_squeeze == "SQUEEZE 🔥":
        score += 3
    elif bb_squeeze == "Sempit":
        score += 1

    if obv_trend == "Rising ↑":
        score += 2

    if vol_trend_ratio >= 1.3:
        score += 2
    elif vol_trend_ratio >= 1.1:
        score += 1

    if price_tightness < 3.0:
        score += 1

    if mfi_change_5d > 0:
        score += 1

    if adx_trend == "Rising":
        score += 1

    if is_adx_bullish:
        score += 1

    if 0 < free_float < 15:
        score += 1

    if has_bearish_div:
        score -= 2

    if last_rsi > 70:
        score -= 1

    if is_above_ma20 != "YA":
        score -= 1

    return max(0, min(score, 10))


def is_silent_accumulation_candidate(
    silent_score: int,
    min_silent_score: int,
    bb_squeeze: str,
    obv_trend: str,
    vol_trend_ratio: float,
    has_bearish_div: bool,
    last_rsi: float,
    avg_vol20_lot: float,
    min_vol_silent_lot: float,
) -> bool:
    """
    Kandidat Silent Accumulation:
    - Lolos volume minimum yang lebih rendah (bukan filter utama)
    - Skor silent >= threshold
    - Minimal 1 dari: BB Squeeze ATAU OBV Rising ATAU Vol Trend >= 1.2
    - Tidak divergence, tidak overbought
    """
    if has_bearish_div:
        return False
    if last_rsi > 75:
        return False
    if avg_vol20_lot < min_vol_silent_lot:
        return False
    if silent_score < min_silent_score:
        return False
    # Minimal ada 1 sinyal kuat
    has_key_signal = (
        bb_squeeze in ("SQUEEZE 🔥", "Sempit")
        or obv_trend == "Rising ↑"
        or vol_trend_ratio >= 1.2
    )
    return has_key_signal

# ─────────────────────────────────────────────
# 5e. COMPOSITE EXPLOSIVE RANK
# ─────────────────────────────────────────────
def compute_composite_rank(
    last_adx: float,
    adx_trend: str,
    price_tightness: float,
    vol_trend_ratio: float,
    free_float: float,
    early_score: int,
    silent_score: int,
    dist_20high: float,
    obv_trend: str,
    has_bearish_div: bool,
) -> tuple[int, list[str]]:
    """
    Composite Explosive Rank (0–10): mendeteksi saham dengan energi terkompresi
    sebelum breakout. Menggabungkan kekuatan tren, akumulasi tersembunyi, dan
    potensi explosive move.

    Komponen:
      +2  ADX > 50 + ADX Trend Rising  (tren sangat kuat — anomali untuk sideways)
      +1  ADX > 25 + ADX Trend Rising  (tren moderat-kuat)
      +2  Price Tightness < 3%         (harga sangat ketat = konsolidasi/akumulasi)
      +1  Price Tightness < 5%         (harga relatif ketat)
      +2  Vol Trend Ratio > 2.0        (volume diam-diam naik signifikan)
      +1  Vol Trend Ratio > 1.3        (volume mulai naik)
      +2  Free Float < 20%             (float kecil = explosive potential)
      +1  Free Float < 35%             (float sedang-kecil)
      +1  OBV Rising                   (konfirmasi uang masuk dari OBV)
      +1  Dist to 20D High > -5%       (sangat dekat resistance, tinggal sedikit trigger)
      -2  Bearish Divergence           (sinyal pembalikan)
    """
    score = 0
    criteria = []

    if last_adx > 50 and adx_trend == "Rising":
        score += 2
        criteria.append(f"ADX {last_adx:.0f} Very Strong+Rising")
    elif last_adx > 25 and adx_trend == "Rising":
        score += 1
        criteria.append(f"ADX {last_adx:.0f} Rising")

    if price_tightness < 3.0:
        score += 2
        criteria.append(f"Tightness {price_tightness:.1f}% (sangat ketat)")
    elif price_tightness < 5.0:
        score += 1
        criteria.append(f"Tightness {price_tightness:.1f}%")

    if vol_trend_ratio > 2.0:
        score += 2
        criteria.append(f"Vol Trend {vol_trend_ratio:.2f}x (akumulasi kuat)")
    elif vol_trend_ratio > 1.3:
        score += 1
        criteria.append(f"Vol Trend {vol_trend_ratio:.2f}x")

    if 0 < free_float < 20:
        score += 2
        criteria.append(f"Float {free_float:.1f}% (kecil)")
    elif free_float < 35:
        score += 1
        criteria.append(f"Float {free_float:.1f}%")

    if obv_trend == "Rising ↑":
        score += 1
        criteria.append("OBV Rising")

    if dist_20high >= -5.0:
        score += 1
        criteria.append(f"Dekat Resistance ({dist_20high:.1f}%)")

    if has_bearish_div:
        score -= 2
        criteria.append("⚠️ Bearish Div (-2)")

    final_score = max(0, min(score, 10))
    return final_score, criteria

def style_composite_rank(val):
    """Styling untuk Composite Explosive Rank"""
    try:
        num = float(val)
        if num >= 8: return 'background-color: #185FA5; color: white; font-weight: bold'
        if num >= 6: return 'background-color: #378ADD; color: white; font-weight: bold'
        if num >= 4: return 'background-color: #B5D4F4; color: #042C53; font-weight: bold'
    except:
        pass
    return ''

# ─────────────────────────────────────────────
# 5f. VISUAL CHART ANALYSIS — B1 (Rule-Based)
# ─────────────────────────────────────────────

def detect_candlestick_pattern(open_s: pd.Series, high_s: pd.Series,
                                low_s: pd.Series, close_s: pd.Series) -> str:
    """
    Deteksi pola candlestick dari OHLC terakhir.
    Returns: label pola atau '' jika tidak ada pola terdeteksi.
    """
    if len(close_s) < 2:
        return ""
    o, h, l, c = float(open_s.iloc[-1]), float(high_s.iloc[-1]), float(low_s.iloc[-1]), float(close_s.iloc[-1])
    o2, c2 = float(open_s.iloc[-2]), float(close_s.iloc[-2])
    body = abs(c - o)
    candle_range = h - l if h > l else 1
    body_pct = body / candle_range

    # Doji: body sangat kecil
    if body_pct < 0.1:
        return "Doji"

    # Hammer: lower shadow panjang, body kecil di atas, sedikit upper shadow
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    if lower_shadow >= 2 * body and upper_shadow < body and c > l:
        return "Hammer 🔨" if c >= o else "Hanging Man"

    # Bullish Engulfing: candle sebelumnya bearish, sekarang bullish dan body lebih besar
    if c > o and c2 < o2 and c > o2 and o < c2:
        return "Bullish Engulfing 🟢"

    # Bearish Engulfing: candle sebelumnya bullish, sekarang bearish dan body lebih besar
    if c < o and c2 > o2 and c < o2 and o > c2:
        return "Bearish Engulfing 🔴"

    # Shooting Star: upper shadow panjang, body kecil di bawah
    if upper_shadow >= 2 * body and lower_shadow < body and c < h:
        return "Shooting Star ⭐"

    return ""


def compute_support_resistance(high_s: pd.Series, low_s: pd.Series,
                                close_s: pd.Series, n: int = 20) -> dict:
    """
    Hitung support/resistance sederhana dari pivot high/low dalam N hari terakhir.
    Returns dict: {resistance, support, dist_to_resistance_pct, dist_to_support_pct}
    """
    if len(high_s) < n:
        return {"resistance": None, "support": None, "dist_resistance_pct": 0.0, "dist_support_pct": 0.0}
    h_tail = high_s.tail(n)
    l_tail = low_s.tail(n)
    resistance = float(h_tail.max())
    support    = float(l_tail.min())
    last_price = float(close_s.iloc[-1])
    dist_r = ((resistance - last_price) / last_price * 100) if last_price > 0 else 0.0
    dist_s = ((last_price - support) / last_price * 100) if last_price > 0 else 0.0
    return {
        "resistance": resistance,
        "support": support,
        "dist_resistance_pct": round(dist_r, 2),
        "dist_support_pct":    round(dist_s, 2),
    }


def compute_trendline_slope(close_s: pd.Series, n: int = 20) -> str:
    """
    Hitung slope linear regression harga dalam N hari terakhir.
    Returns: 'Up ↗', 'Down ↘', atau 'Flat →'
    """
    if len(close_s) < n:
        return "Flat →"
    tail = close_s.tail(n).values
    x    = np.arange(len(tail))
    slope = np.polyfit(x, tail, 1)[0]
    avg_price = tail.mean()
    slope_pct = (slope / avg_price) * 100 if avg_price > 0 else 0
    if slope_pct > 0.3:
        return "Up ↗"
    elif slope_pct < -0.3:
        return "Down ↘"
    return "Flat →"


def detect_volume_climax(volume_s: pd.Series, n: int = 20, threshold: float = 3.0) -> bool:
    """
    Deteksi volume climax: hari ini > threshold × rata-rata N hari.
    """
    if len(volume_s) < n + 1:
        return False
    avg = float(volume_s.iloc[-(n+1):-1].mean())
    today_vol = float(volume_s.iloc[-1])
    return (today_vol > threshold * avg) if avg > 0 else False


def detect_consolidation_breakout(close_s: pd.Series, n: int = 10, tight_pct: float = 3.0) -> bool:
    """
    Deteksi consolidation breakout: harga keluar dari range sempit N hari lalu.
    Syarat: CV harga N-1 hari sebelumnya < tight_pct, dan hari ini close > max range tsb.
    """
    if len(close_s) < n + 2:
        return False
    prev_range = close_s.iloc[-(n+1):-1]
    cv = (prev_range.std() / prev_range.mean() * 100) if prev_range.mean() > 0 else 100
    if cv > tight_pct:
        return False
    prev_high = float(prev_range.max())
    today = float(close_s.iloc[-1])
    return today > prev_high


def compute_visual_chart_analysis(
    open_s: pd.Series, high_s: pd.Series, low_s: pd.Series,
    close_s: pd.Series, volume_s: pd.Series,
) -> str:
    """
    Kombinasi semua rule-based visual analysis → satu string ringkasan singkat.
    """
    signals = []

    # 1. Candlestick pattern
    candle = detect_candlestick_pattern(open_s, high_s, low_s, close_s)
    if candle:
        signals.append(candle)

    # 2. Volume climax
    if detect_volume_climax(volume_s, n=20, threshold=3.0):
        signals.append("Vol Climax 💥")

    # 3. Consolidation breakout
    if detect_consolidation_breakout(close_s, n=10, tight_pct=3.0):
        signals.append("Consol Breakout 🚀")

    # 4. Trendline slope
    slope = compute_trendline_slope(close_s, n=20)
    signals.append(f"Trend:{slope}")

    # 5. Dekat resistance (< 2% dari high 20D)
    sr = compute_support_resistance(high_s, low_s, close_s, n=20)
    if sr["dist_resistance_pct"] <= 2.0 and sr["dist_resistance_pct"] >= 0:
        signals.append(f"Dekat R({sr['dist_resistance_pct']:.1f}%)")
    elif sr["dist_resistance_pct"] <= 5.0 and sr["dist_resistance_pct"] >= 0:
        signals.append(f"Menuju R({sr['dist_resistance_pct']:.1f}%)")

    return " | ".join(signals) if signals else "-"


def style_visual_chart(val):
    val = str(val)
    if "Bullish Engulfing" in val or "Consol Breakout" in val:
        return "background-color: rgba(0,180,0,0.18); color: #004d00; font-weight:bold"
    if "Bearish Engulfing" in val or "Shooting Star" in val:
        return "background-color: rgba(255,60,60,0.15); color: darkred;"
    if "Vol Climax" in val:
        return "background-color: rgba(255,165,0,0.25); color: #7a4000; font-weight:bold"
    if "Hammer" in val:
        return "background-color: rgba(100,200,100,0.2);"
    return ""


# ─────────────────────────────────────────────
# 5g. PLOTLY CANDLESTICK CHART — B2
# ─────────────────────────────────────────────

@st.cache_data(ttl=1800)
def fetch_ohlcv_for_plotly(ticker_jk: str, days: int = 90):
    """Fetch OHLCV data untuk Plotly chart."""
    try:
        df = yf.download(ticker_jk, period=f"{days}d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        # Flatten MultiIndex columns jika ada
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open','High','Low','Close','Volume']].copy()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA50'] = df['Close'].rolling(50).mean()
        # Support & Resistance dari high/low 20D rolling
        df['Resist20'] = df['High'].rolling(20).max()
        df['Support20'] = df['Low'].rolling(20).min()
        return df
    except Exception as e:
        return None


def show_plotly_candlestick(ticker_code: str, chart_key: str = "plotly_chart"):
    """
    Tampilkan Plotly candlestick chart interaktif dengan MA, Volume, Support/Resistance.
    """
    ticker_jk = ticker_code + ".JK"
    with st.spinner(f"Memuat chart Plotly untuk {ticker_code}…"):
        df = fetch_ohlcv_for_plotly(ticker_jk)

    if df is None or df.empty:
        st.warning(f"Data OHLCV tidak tersedia untuk {ticker_code}.")
        return

    # Pastikan kolom dalam bentuk Series 1D (bukan DataFrame)
    def _s(col):
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        return s

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.70, 0.30],
        subplot_titles=[f"{ticker_code} – Candlestick + MA", "Volume"]
    )

    # ── Candlestick ──
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=_s('Open'), high=_s('High'),
        low=_s('Low'),  close=_s('Close'),
        name="OHLC",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # ── MA Lines ──
    fig.add_trace(go.Scatter(
        x=df.index, y=_s('MA20'),
        name="MA20", line=dict(color="#FF9800", width=1.5),
        opacity=0.85,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=_s('MA50'),
        name="MA50", line=dict(color="#2196F3", width=1.5),
        opacity=0.85,
    ), row=1, col=1)

    # ── Resistance & Support (20D rolling) ──
    fig.add_trace(go.Scatter(
        x=df.index, y=_s('Resist20'),
        name="Resist 20D", line=dict(color="#ef5350", width=1, dash="dot"),
        opacity=0.6,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=_s('Support20'),
        name="Support 20D", line=dict(color="#26a69a", width=1, dash="dot"),
        opacity=0.6,
    ), row=1, col=1)

    # ── Volume bar (color by price direction) ──
    close_arr = _s('Close').values
    open_arr  = _s('Open').values
    vol_colors = ["#26a69a" if c >= o else "#ef5350" for c, o in zip(close_arr, open_arr)]
    fig.add_trace(go.Bar(
        x=df.index, y=_s('Volume'),
        name="Volume", marker_color=vol_colors, opacity=0.75,
    ), row=2, col=1)

    # ── Volume MA20 ──
    vol_ma = _s('Volume').rolling(20).mean()
    fig.add_trace(go.Scatter(
        x=df.index, y=vol_ma,
        name="Vol MA20", line=dict(color="#FF9800", width=1.2),
        opacity=0.8,
    ), row=2, col=1)

    fig.update_layout(
        height=550,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        margin=dict(l=30, r=20, t=40, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,249,250,1)",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e0e0e0")
    fig.update_yaxes(showgrid=True, gridcolor="#e0e0e0")

    st.plotly_chart(fig, use_container_width=True, key=chart_key)

    # Tambahan: ringkasan sinyal visual
    c = df['Close']
    h = df['High']
    l = df['Low']
    v = df['Volume']
    o = df['Open']

    def _col_series(col):
        s = df[col]
        return s.iloc[:,0] if isinstance(s, pd.DataFrame) else s

    candle_pat = detect_candlestick_pattern(_col_series('Open'), _col_series('High'), _col_series('Low'), _col_series('Close'))
    vol_climax  = detect_volume_climax(_col_series('Volume'))
    consol_bo   = detect_consolidation_breakout(_col_series('Close'))
    slope       = compute_trendline_slope(_col_series('Close'))
    sr          = compute_support_resistance(_col_series('High'), _col_series('Low'), _col_series('Close'))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Candlestick", candle_pat if candle_pat else "-")
    col2.metric("Trendline", slope)
    col3.metric("Vol Climax", "✅ Ya" if vol_climax else "—")
    col4.metric("Consol Breakout", "✅ Ya" if consol_bo else "—")

    c2a, c2b = st.columns(2)
    if sr["resistance"]:
        c2a.metric("Resistance 20D", f"Rp {sr['resistance']:,.0f}",
                   f"{sr['dist_resistance_pct']:+.1f}% dari harga")
        c2b.metric("Support 20D",    f"Rp {sr['support']:,.0f}",
                   f"-{sr['dist_support_pct']:.1f}% dari harga")


# ─────────────────────────────────────────────
# 6. FUNGSI ANALISA UTAMA v16
# ─────────────────────────────────────────────
def get_signals_and_data(df_c, df_v, df_h, df_l, df_o, df_ref, min_vol_lot,
                          min_mfi_change_watch, min_early_score,
                          watch_require_outperform,
                          min_vol_silent_lot, min_silent_score):
    results = []
    shortlist_keys = []
    prebreakout_keys = []
    silent_accum_keys = []
    min_vol_lembar = min_vol_lot * 100
    min_vol_silent_lembar = min_vol_silent_lot * 100
    ff_lookup = dict(zip(df_ref['Kode Saham'], df_ref['Free Float']))

    ihsg_c = df_c["^JKSE"].dropna() if "^JKSE" in df_c.columns else pd.Series()
    ihsg_perf = ((ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20]
                 if len(ihsg_c) >= 20 else 0)

    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col):
            continue

        c = df_c[col].dropna()
        v = df_v[col].dropna()
        h = df_h[col].dropna()
        l = df_l[col].dropna()
        # Open series (untuk candlestick pattern detection)
        o_col = df_o[col].dropna() if col in df_o.columns else pd.Series(dtype=float)

        if len(c) < 55:
            continue

        # ── Volume filter ──
        # Gunakan min_vol_silent_lembar sebagai floor absolut agar saham low-cap tetap masuk proses
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        avg_vol50 = v.rolling(50).mean().iloc[-1]
        if avg_vol20 < min_vol_silent_lembar:   # filter paling longgar (silent threshold)
            continue
        # Flag apakah lolos filter utama (untuk shortlist & pre-breakout)
        passes_main_vol = avg_vol20 >= min_vol_lembar

        rel_vol_20 = v.iloc[-1] / avg_vol20 if avg_vol20 > 0 else 0.0
        rel_vol_50 = v.iloc[-1] / avg_vol50 if avg_vol50 > 0 else 0.0
        rel_vol = min(rel_vol_20, rel_vol_50 * 1.2)

        p_change_today = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2]) * 100

        # ── Consecutive Up Days ──
        consecutive_up = 0
        for i in range(1, 7):
            if len(c) > i and c.iloc[-i] > c.iloc[-i - 1]:
                consecutive_up += 1
            else:
                break

        # ── RSI ──
        rsi_series = pta.rsi(close=c, length=14)
        last_rsi = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else 50.0

        # ── ADX + DI+ / DI- ──
        adx_df = pta.adx(high=h, low=l, close=c, length=14)
        if adx_df is not None and not adx_df.empty:
            last_adx  = float(adx_df['ADX_14'].iloc[-1])
            last_dmp  = float(adx_df['DMP_14'].iloc[-1])
            last_dmn  = float(adx_df['DMN_14'].iloc[-1])

            adx_direction  = "Bullish (DI+>DI-)" if last_dmp > last_dmn else "Bearish (DI->DI+)"
            is_adx_bullish = last_dmp > last_dmn

            adx_prev3 = adx_df['ADX_14'].iloc[-4:-1].mean()
            if last_adx > adx_prev3 + 0.5:
                adx_trend = "Rising"
            elif last_adx < adx_prev3 - 0.5:
                adx_trend = "Falling"
            else:
                adx_trend = "Flat"

            if last_adx >= 40:   adx_strength = "Very Strong"
            elif last_adx >= 25: adx_strength = "Strong"
            elif last_adx >= 20: adx_strength = "Moderate"
            else:                adx_strength = "Weak"
        else:
            last_adx = last_dmp = last_dmn = 0.0
            adx_direction = adx_trend = adx_strength = "N/A"
            is_adx_bullish = False

        # ── MFI ──
        tp = (h + l + c) / 3
        mf = tp * v
        pos_mf = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg_mf = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        mfi_series = 100 - (100 / (1 + (pos_mf / neg_mf).replace([np.inf, -np.inf], np.nan)))
        last_mfi = float(mfi_series.iloc[-1]) if not mfi_series.empty else 50.0
        mfi_change_5d = float(last_mfi - mfi_series.iloc[-6]) if len(mfi_series) >= 6 else 0.0

        # ── MA20 & 20D Breakout ──
        ma20 = c.rolling(20).mean().iloc[-1]
        is_above_ma20 = "YA" if c.iloc[-1] > ma20 else "TIDAK"
        high_20 = h.rolling(20).max().iloc[-1]
        is_breakout = "YA" if c.iloc[-1] >= high_20 * 0.99 else "TIDAK"
        dist_20high = round((c.iloc[-1] / high_20 - 1) * 100, 2) if high_20 > 0 else 0.0

        # ── PVA ──
        pva = "Neutral"
        if p_change_today > 1.0 and rel_vol > 2.0:
            pva = "Strong Bullish Vol"
        elif p_change_today > 0.5 and rel_vol > 1.5:
            pva = "Bullish Vol"
        elif p_change_today < -0.6 and rel_vol > 1.5:
            pva = "Bearish Vol"

        # ── Market RS ──
        ticker_name = str(col).replace('.JK', '').upper()
        stock_perf = ((c.iloc[-1] - c.iloc[-20]) / c.iloc[-20]) if len(c) >= 20 else 0
        rs = "Outperform" if stock_perf > ihsg_perf else "Underperform"

        # ── Bearish Divergence ──
        has_bearish_div = detect_bearish_divergence(c, mfi_series, window=10)
        divergence_warning = "⚠️ Bearish Divergence" if has_bearish_div else ""

        # ── Free Float ──
        free_float = float(ff_lookup.get(ticker_name, 0.0))

        # ── CHART ANALYSIS ──
        chart_analysis = get_chart_analysis(
            close=c, ma20=ma20, last_rsi=last_rsi, last_adx=last_adx,
            is_adx_bullish=is_adx_bullish, is_breakout=is_breakout,
            dist_20high=dist_20high, mfi_change_5d=mfi_change_5d,
            p_change_today=p_change_today, rel_vol=rel_vol,
        )

        # ── OPSI C: EARLY MOMENTUM SCORE ──
        early_score = compute_early_momentum_score(
            mfi_change_5d=mfi_change_5d,
            adx_trend=adx_trend,
            is_above_ma20=is_above_ma20,
            is_adx_bullish=is_adx_bullish,
            rs=rs,
            last_rsi=last_rsi,
            free_float=free_float,
            has_bearish_div=has_bearish_div,
        )

        # ── V18: SILENT ACCUMULATION INDICATORS ──
        bb_squeeze_label, bb_width_pct = detect_bb_squeeze(c, window=20)
        obv_trend_label   = compute_obv_trend(c, v, lookback=10)
        vol_trend_ratio   = compute_vol_trend_ratio(v, short=5, long=20)
        price_tightness   = compute_price_tightness(c, lookback=10)
        avg_vol20_lot     = avg_vol20 / 100

        silent_score = compute_silent_score(
            bb_squeeze      = bb_squeeze_label,
            obv_trend       = obv_trend_label,
            vol_trend_ratio = vol_trend_ratio,
            price_tightness = price_tightness,
            mfi_change_5d   = mfi_change_5d,
            adx_trend       = adx_trend,
            is_adx_bullish  = is_adx_bullish,
            free_float      = free_float,
            has_bearish_div = has_bearish_div,
            last_rsi        = last_rsi,
            is_above_ma20   = is_above_ma20,
        )

        # ── COMPOSITE EXPLOSIVE RANK ──
        comp_rank, comp_criteria = compute_composite_rank(
            last_adx        = last_adx,
            adx_trend       = adx_trend,
            price_tightness = price_tightness,
            vol_trend_ratio = vol_trend_ratio,
            free_float      = free_float,
            early_score     = early_score,
            silent_score    = silent_score,
            dist_20high     = dist_20high,
            obv_trend       = obv_trend_label,
            has_bearish_div = has_bearish_div,
        )

        # ── VISUAL CHART ANALYSIS (B1) ──
        visual_analysis = compute_visual_chart_analysis(
            open_s=o_col, high_s=h, low_s=l, close_s=c, volume_s=v
        )

        # ── REASONS ──
        reasons = []
        if rel_vol >= 2.0 and p_change_today > 1.0:
            reasons.append("Extreme Volume Surge")
        if is_above_ma20 == "YA" and last_mfi < 55:
            reasons.append("Above MA20 + MFI Fresh")
        if consecutive_up >= 3 and mfi_change_5d > 8.0:
            reasons.append("Consec Up + MFI Rising")
        if last_adx > 25 and is_adx_bullish and last_mfi > 55 and mfi_change_5d > 8.0:
            reasons.append("Strong Trend + MFI Rising (DI+>DI-)")
        if is_above_ma20 == "YA" and last_rsi < 75 and is_breakout == "YA":
            reasons.append("Above MA20 + Breakout")

        # ── SHORTLIST LOGIC v13 ──
        is_shortlist = (
            passes_main_vol          # harus lolos filter volume utama
            and len(reasons) >= 3
            and rs == "Outperform"
            and is_above_ma20 == "YA"
            and last_mfi >= 55
            and last_mfi < 85
            and last_adx > 22
            and is_adx_bullish
            and adx_trend != "Falling"
            and not has_bearish_div
        )

        if is_shortlist:
            shortlist_keys.append(ticker_name)

        # ── OPSI A: PRE-BREAKOUT WATCH LIST ──
        watch_rs_ok = (rs == "Outperform") if watch_require_outperform else True
        is_watch = (
            passes_main_vol          # harus lolos filter volume utama
            and not is_shortlist
            and watch_rs_ok
            and is_prebreakout_candidate(
                mfi_change_5d=mfi_change_5d,
                adx_trend=adx_trend,
                is_above_ma20=is_above_ma20,
                is_adx_bullish=is_adx_bullish,
                rs=rs,
                consecutive_up=consecutive_up,
                is_breakout=is_breakout,
                rel_vol_20=rel_vol_20,
                has_bearish_div=has_bearish_div,
                min_mfi_change_watch=min_mfi_change_watch,
                early_score=early_score,
                min_early_score=min_early_score,
            )
        )

        # ── V18: SILENT ACCUMULATION ──
        is_silent = (
            not is_shortlist
            and not is_watch
            and is_silent_accumulation_candidate(
                silent_score      = silent_score,
                min_silent_score  = min_silent_score,
                bb_squeeze        = bb_squeeze_label,
                obv_trend         = obv_trend_label,
                vol_trend_ratio   = vol_trend_ratio,
                has_bearish_div   = has_bearish_div,
                last_rsi          = last_rsi,
                avg_vol20_lot     = avg_vol20_lot,
                min_vol_silent_lot= min_vol_silent_lot,
            )
        )

        if is_watch:
            prebreakout_keys.append(ticker_name)
        if is_silent:
            silent_accum_keys.append(ticker_name)

        results.append({
            'Kode Saham':            ticker_name,
            'Free Float (%)':        free_float,
            'MFI (14D)':             float(last_mfi),
            'MFI Change 5D':         float(mfi_change_5d),
            'RSI (14)':              float(last_rsi),
            'ADX (14)':              float(last_adx),
            'ADX Direction':         adx_direction,
            'ADX Trend':             adx_trend,
            'ADX Strength':          adx_strength,
            'Divergence Warning':    divergence_warning,
            'PVA':                   pva,
            'Market RS':             rs,
            'Above MA20':            is_above_ma20,
            '20D Breakout':          is_breakout,
            'Dist to 20D High (%)':  dist_20high,
            'Last Price':            int(round(c.iloc[-1])),
            'Rel Vol (20D)':         float(rel_vol_20),
            'Rel Vol (50D)':         float(rel_vol_50),
            'Consec Up Days':        consecutive_up,
            'AvgVol20 (Lot)':        int(avg_vol20 / 100),
            'Early Momentum Score':  early_score,
            'Pre-Breakout Watch':    '🔭 Watch' if is_watch else '',
            # V18: Silent Accumulation columns
            'BB Squeeze':            bb_squeeze_label,
            'BB Width (%)':          bb_width_pct,
            'OBV Trend':             obv_trend_label,
            'Vol Trend Ratio':       vol_trend_ratio,
            'Price Tightness (%)':   price_tightness,
            'Silent Score':          silent_score,
            'Silent Accum':          '🕵️ Silent' if is_silent else '',
            'Composite Rank':        comp_rank,
            'Composite Criteria':    " | ".join(comp_criteria),
            'Shortlist Reasons':     ", ".join(reasons) if reasons else "",
            'Chart Analysis':        chart_analysis,
            'Visual Chart Analysis': visual_analysis,
        })

    df_results = pd.DataFrame(results)
    return df_results, shortlist_keys, prebreakout_keys, silent_accum_keys

# ─────────────────────────────────────────────
# 6b. AI CHART ANALYSIS ENGINE (v15)
# ─────────────────────────────────────────────

CHART_LABELS = [
    "Overextended 🚨",
    "Breakout Valid 🚀",
    "Pullback Healthy 👍",
    "Uptrend Normal",
    "Downtrend ❌",
    "Sideways / Konsolidasi",
]

@st.cache_data(ttl=1800)
def screenshot_yahoo_chart(ticker_jk: str) -> bytes | None:
    try:
        from playwright.sync_api import sync_playwright
        url = f"https://finance.yahoo.com/quote/{ticker_jk}/"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.click('button:has-text("Accept")', timeout=3000)
            except Exception:
                pass
            try:
                page.click('button:has-text("Reject all")', timeout=2000)
            except Exception:
                pass
            try:
                page.wait_for_selector('canvas, [data-testid="chart-container"]', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            png = page.screenshot(clip={"x": 0, "y": 140, "width": 1280, "height": 420})
            browser.close()
            return png
    except Exception:
        return None


@st.cache_data(ttl=1800)
def fetch_ohlcv_summary(ticker_jk: str) -> str:
    try:
        df = yf.download(ticker_jk, period="90d", progress=False, auto_adjust=True)
        if df.empty:
            return "Data OHLCV tidak tersedia."
        df = df.tail(60)
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        last = df.iloc[-1]
        prev5 = df.iloc[-6]
        high20 = df["High"].rolling(20).max().iloc[-1]
        low20  = df["Low"].rolling(20).min().iloc[-1]
        avg_vol20 = df["Volume"].rolling(20).mean().iloc[-1]
        rel_vol = float(df["Volume"].iloc[-1]) / float(avg_vol20) if avg_vol20 > 0 else 0

        lines = [
            f"Ticker: {ticker_jk}",
            f"Tanggal terakhir: {df.index[-1].date()}",
            f"Harga Close terakhir: {float(last['Close']):.0f}",
            f"Open: {float(last['Open']):.0f}  High: {float(last['High']):.0f}  Low: {float(last['Low']):.0f}",
            f"Volume hari ini: {int(last['Volume']):,}  (Rel Vol vs MA20: {rel_vol:.2f}x)",
            f"MA20: {float(last['MA20']):.0f}  MA50: {float(last['MA50']):.0f}",
            f"High 20D: {float(high20):.0f}  Low 20D: {float(low20):.0f}",
            f"Perubahan harga 5D: {((float(last['Close']) - float(prev5['Close'])) / float(prev5['Close']) * 100):.2f}%",
            "",
            "30 candle terakhir (Date,O,H,L,C,Vol):",
        ]
        for idx, row in df.tail(30).iterrows():
            lines.append(
                f"{idx.date()}, O={float(row['Open']):.0f}, H={float(row['High']):.0f}, "
                f"L={float(row['Low']):.0f}, C={float(row['Close']):.0f}, "
                f"Vol={int(row['Volume']):,}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetch OHLCV: {e}"


def ai_chart_analysis(ticker_code: str) -> dict:
    ticker_jk = ticker_code + ".JK"
    ohlcv_text = fetch_ohlcv_summary(ticker_jk)
    png_bytes = screenshot_yahoo_chart(ticker_jk)
    has_screenshot = png_bytes is not None

    label_list = "\n".join(f"- {lb}" for lb in CHART_LABELS)
    system_prompt = (
        "Kamu adalah analis teknikal saham BEI (Bursa Efek Indonesia) berpengalaman. "
        "Tugasmu: analisa chart dan data OHLCV yang diberikan, lalu tentukan satu label kondisi chart. "
        "Perhatikan: pola candlestick, posisi harga vs MA20/MA50, tren, volume, breakout, pullback, dan divergensi. "
        "Jawab HANYA dalam JSON, tidak ada teks lain, format:\n"
        '{"label": "<pilih satu label>", "reasoning": "<1-2 kalimat alasan singkat dalam Bahasa Indonesia>"}\n'
        f"\nLabel yang tersedia:\n{label_list}"
    )

    user_content = []
    if has_screenshot:
        b64_img = base64.b64encode(png_bytes).decode("utf-8")
        user_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64_img}
        })
        user_content.append({
            "type": "text",
            "text": f"Ini adalah screenshot chart Yahoo Finance untuk saham {ticker_code}.\n\nBerikut data OHLCV 30 hari terakhir:\n\n{ohlcv_text}"
        })
    else:
        user_content.append({
            "type": "text",
            "text": f"Screenshot chart tidak tersedia. Analisa berdasarkan data OHLCV saja.\n\n{ohlcv_text}"
        })

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 300,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}]
    }

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = "".join(
            blk.get("text", "") for blk in data.get("content", []) if blk.get("type") == "text"
        )
        clean = raw_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        label = parsed.get("label", "Sideways / Konsolidasi")
        if not any(lb in label for lb in CHART_LABELS):
            label = "Sideways / Konsolidasi"
        return {"label": label, "reasoning": parsed.get("reasoning", ""), "has_screenshot": has_screenshot}
    except Exception as e:
        return {"label": "Sideways / Konsolidasi", "reasoning": f"Error analisa: {e}", "has_screenshot": has_screenshot}


# ─────────────────────────────────────────────
# 7. SIDEBAR
# ─────────────────────────────────────────────
st.sidebar.header("⚙️ Konfigurasi v16")

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect(
    "Pilih Saham (Kosongkan = Semua):", options=target_list)

min_p       = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p       = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=100000)
max_ff      = float(st.sidebar.slider("Maximal Free Float (%)", 0.0, 100.0, 100.0))

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Filter Shortlist Utama")
min_mfi_change   = st.sidebar.number_input("Min MFI Change 5D", value=8.0, step=0.5)
min_adx          = st.sidebar.number_input("Min ADX (14)", value=22, step=1)
only_outperform  = st.sidebar.checkbox("Hanya Market RS = Outperform", value=True)
show_breakout_only = st.sidebar.checkbox("Hanya 20D Breakout", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Filter Proteksi v13")
only_adx_bullish    = st.sidebar.checkbox("Hanya DI+ > DI- (ADX Bullish)", value=True)
exclude_adx_falling = st.sidebar.checkbox("Exclude ADX Trend = Falling", value=True)
exclude_divergence  = st.sidebar.checkbox("Exclude Bearish Divergence", value=True)

# ── SIDEBAR OPSI A & C (BARU) ──
st.sidebar.markdown("---")
st.sidebar.subheader("🔭 Opsi A: Pre-Breakout Watch List")
st.sidebar.caption("Tangkap saham yang BELUM breakout tapi MFI sudah terbakar. "
                   "Contoh: MDIA 17 April — MFI Change +72.7 tapi Consec Up = 0.")
enable_prebreakout   = st.sidebar.checkbox("Aktifkan Pre-Breakout Watch List", value=True)
min_mfi_change_watch = st.sidebar.number_input(
    "Min MFI Change 5D untuk Watch", value=20.0, step=1.0,
    help="Default 20 = uang sudah masuk signifikan meski belum terlihat di harga")
watch_require_outperform = st.sidebar.checkbox(
    "Hanya Outperform vs IHSG (Watch)", value=False,
    help="Matikan untuk tidak mensyaratkan Market RS = Outperform di pre-breakout")

st.sidebar.markdown("---")
st.sidebar.subheader("🕵️ V18: Silent Accumulation Radar")
st.sidebar.caption(
    "Mendeteksi akumulasi diam-diam seperti pola KOTA sebelum terbang. "
    "Menggunakan BB Squeeze + OBV + Vol Trend — tidak butuh volume besar."
)
enable_silent        = st.sidebar.checkbox("Aktifkan Silent Accumulation Radar", value=True)
min_vol_silent_lot   = st.sidebar.number_input(
    "Min Avg Vol 20D untuk Silent (LOT)", value=10000, step=1000,
    help="Jauh lebih rendah dari filter utama. Menangkap saham low-cap yang diakumulasi diam-diam.")
min_silent_score     = st.sidebar.slider(
    "Min Silent Accumulation Score", min_value=0, max_value=10, value=5,
    help="≥6 = sinyal kuat. ≥8 = potensi explosive (tapi sabar, belum tentu langsung naik)")
silent_require_squeeze = st.sidebar.checkbox(
    "Wajib BB Squeeze / Sempit", value=False,
    help="Aktifkan untuk hanya tampilkan kandidat dengan Bollinger Band sedang menyempit")
st.sidebar.caption("Skor 0–10 gabungan: MFI Change + ADX Rising + MA20 + RSI + Float kecil. "
                   "Saham dengan skor tinggi tapi belum shortlist = kandidat liar.")
min_early_score = st.sidebar.slider(
    "Min Early Momentum Score untuk Watch", min_value=0, max_value=10, value=5,
    help="Skor ≥ 6 = kandidat kuat. Skor ≥ 8 = potensi explosive (tapi berisiko)")
show_score_in_table = st.sidebar.checkbox("Tampilkan kolom Early Momentum Score", value=True)
show_composite_rank = st.sidebar.checkbox("Tampilkan Composite Explosive Rank", value=True,
    help="Skor 0–10 gabungan: ADX kuat + harga ketat + volume naik diam-diam + float kecil. "
         "≥8 = prioritas tertinggi untuk entry sebelum breakout.")

today = date.today()
end_d = st.sidebar.date_input("📅 Analisa per tanggal", today)
st.sidebar.caption("ℹ️ Data historis otomatis diambil 120 hari ke belakang untuk keakuratan indikator.")

# ── SIDEBAR BROKER SUMMARY (v20) ──
st.sidebar.markdown("---")
st.sidebar.subheader("🏦 v20: Broker Summary Analysis")
if True:
    enable_broker   = st.sidebar.checkbox("Aktifkan Broker Summary Analysis", value=True)
    broker_mode     = st.sidebar.radio(
        "Mode Data Broker",
        ["🌐 Auto Fetch RTI", "📁 Upload CSV Manual"],
        help="Auto Fetch: scrape RTI Business otomatis. Upload CSV: dari IDX/RTI/Stockbit manual."
    )
    broker_days     = st.sidebar.slider("Periode Broker Summary (hari)", 5, 60, 30)
    min_broker_score = st.sidebar.slider(
        "Min Broker Score untuk Moonstock", 0, 10, 6,
        help="≥6 = Akumulasi. ≥8 = Akumulasi Kuat. Dipakai untuk filter tab Moonstock Radar."
    )
    st.sidebar.caption(
        "Broker Score 0–10 berdasarkan smart money net buy, rasio asing, dan pola distribusi. "
        "Score ≥6 = akumulasi institusi terdeteksi."
    )
else:
    enable_broker    = False
    broker_mode      = "📁 Upload CSV Manual"
    broker_days      = 30
    min_broker_score = 6
    st.sidebar.warning("⚠️ broker_summary_module.py tidak ditemukan. Letakkan di folder yang sama dengan app ini.")

st.sidebar.markdown("---")
btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True, type="primary")
if st.sidebar.button("🗑️ Clear Cache", use_container_width=True):
    st.cache_data.clear()
    st.sidebar.success("Cache berhasil dibersihkan! Silakan klik JALANKAN ANALISA ulang.")

# ─────────────────────────────────────────────
# 8. FORMAT & STYLE
# ─────────────────────────────────────────────
FORMAT_DICT = {
    'Rel Vol (20D)':         "{:.2f}x",
    'Rel Vol (50D)':         "{:.2f}x",
    'Free Float (%)':        "{:.2f}%",
    'MFI (14D)':             "{:.2f}",
    'MFI Change 5D':         "{:+.2f}",
    'RSI (14)':              "{:.2f}",
    'ADX (14)':              "{:.2f}",
    'Dist to 20D High (%)':  "{:.2f}%",
}

def apply_full_style(df_styled, include_score=True, include_watch=False, include_silent=False, include_broker=False):
    cols = df_styled.data.columns.tolist()

    def _map(style_fn, col):
        nonlocal styled
        if col in cols:
            styled = styled.map(style_fn, subset=[col])

    styled = df_styled.format(FORMAT_DICT, na_rep="-")
    _map(style_mfi,            'MFI (14D)')
    _map(style_market_rs,      'Market RS')
    _map(style_pva,            'PVA')
    _map(style_ma_filter,      'Above MA20')
    _map(style_rel_vol,        'Rel Vol (20D)')
    _map(style_adx,            'ADX (14)')
    _map(style_divergence,     'Divergence Warning')
    _map(style_adx_trend,      'ADX Trend')
    _map(style_adx_dir,        'ADX Direction')
    _map(style_chart_analysis, 'Chart Analysis')
    _map(style_visual_chart,   'Visual Chart Analysis')
    if include_score:
        _map(style_early_momentum, 'Early Momentum Score')
    if include_watch:
        _map(style_prebreakout, 'Pre-Breakout Watch')
    if include_silent:
        _map(style_silent_score, 'Silent Score')
        _map(style_bb_squeeze,   'BB Squeeze')
        _map(style_obv_trend,    'OBV Trend')
    _map(style_composite_rank, 'Composite Rank')
    if include_broker:
        _map(style_broker_score,  'Broker Score')
        _map(style_broker_signal, 'Broker Signal')
    return styled

# ─────────────────────────────────────────────
# 9. OUTPUT UTAMA
# ─────────────────────────────────────────────
# ── Inisialisasi session_state global ──
if "tv_ticker" not in st.session_state:
    st.session_state.tv_ticker = None
if "analisa_hasil" not in st.session_state:
    st.session_state.analisa_hasil = None   # akan diisi dict saat tombol diklik

# ── Jalankan analisa hanya saat tombol diklik ──
if btn_analisa:
    with st.spinner('Menganalisa market…'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk  = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l, df_o = fetch_yf_all_data(tuple(tickers_jk), end_d)

        if not df_c.empty:
            df_res, shortlist, prebreakout_list, silent_list = get_signals_and_data(
                df_c, df_v, df_h, df_l, df_o, df_emiten, min_vol_lot,
                min_mfi_change_watch=min_mfi_change_watch,
                min_early_score=min_early_score,
                watch_require_outperform=watch_require_outperform,
                min_vol_silent_lot=min_vol_silent_lot,
                min_silent_score=min_silent_score,
            )

            # ── BROKER SUMMARY SCORING (v20) ──
            broker_scores = {}
            if enable_broker:
                if broker_mode == "🌐 Auto Fetch RTI":
                    all_tickers_for_broker = df_res['Kode Saham'].tolist()
                    progress_bar = st.progress(0, text="Fetching broker data dari RTI...")
                    def _broker_progress(frac, msg):
                        progress_bar.progress(frac, text=msg)
                    broker_scores = fetch_broker_scores_batch(
                        all_tickers_for_broker,
                        days=broker_days,
                        progress_callback=_broker_progress,
                    )
                    progress_bar.empty()
                # Upload CSV mode: broker_scores akan diisi di render section

                # Tambahkan kolom broker ke df_res (untuk mode auto-fetch)
                if broker_scores:
                    df_res["Broker Score"]    = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("score", 0))
                    df_res["Broker Signal"]   = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("signal", "No Data"))
                    df_res["Smart Net Lot"]   = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("smart_net_lot", 0))
                    df_res["Asing Net Lot"]   = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("asing_net_lot", 0))

                    # Moonstock Score (0–5): gabungan 5 kriteria
                    df_res["Moonstock Score"] = (
                        (df_res["Broker Score"] >= min_broker_score).astype(int) * 2 +
                        (df_res["Early Momentum Score"] >= 6).astype(int) +
                        (df_res["Silent Score"] >= 5).astype(int) +
                        (df_res["Above MA20"] == "YA").astype(int) +
                        (df_res["Market RS"] == "Outperform").astype(int)
                    )
                    moonstock_list = df_res[df_res["Moonstock Score"] >= 4]["Kode Saham"].tolist()
                else:
                    moonstock_list = []
            else:
                moonstock_list = []

            # Re-apply filter setelah kolom broker ditambahkan
            if not df_res.empty:
                mask = (
                    (df_res['Last Price'] >= min_p) &
                    (df_res['Last Price'] <= max_p) &
                    (df_res['Free Float (%)'] <= max_ff) &
                    (df_res['MFI Change 5D'] >= min_mfi_change) &
                    (df_res['ADX (14)'] >= min_adx)
                )
                if only_outperform:
                    mask &= df_res['Market RS'] == 'Outperform'
                if show_breakout_only:
                    mask &= df_res['20D Breakout'] == 'YA'
                if only_adx_bullish:
                    mask &= df_res['ADX Direction'] == 'Bullish (DI+>DI-)'
                if exclude_adx_falling:
                    mask &= df_res['ADX Trend'] != 'Falling'
                if exclude_divergence:
                    mask &= df_res['Divergence Warning'] == ''
                df_res_filtered = df_res[mask]

            # ── Simpan semua hasil ke session_state ──
            st.session_state.analisa_hasil = {
                "df_res":           df_res,
                "shortlist":        shortlist,
                "prebreakout_list": prebreakout_list,
                "silent_list":      silent_list,
                "df_res_filtered":  df_res_filtered,
                "broker_scores":    broker_scores,
                "moonstock_list":   moonstock_list,
            }
            st.session_state.tv_ticker = None  # reset pilihan chart saat analisa baru

        else:
            st.error("Data gagal diambil untuk range tanggal tersebut. Coba perlebar range tanggal.")

# ── Render hasil: dari session_state (tetap tampil saat rerun apapun) ──
if st.session_state.analisa_hasil is not None:
    _h               = st.session_state.analisa_hasil
    df_res           = _h["df_res"]
    shortlist        = _h["shortlist"]
    prebreakout_list = _h["prebreakout_list"]
    silent_list      = _h.get("silent_list", [])
    df_res_filtered  = _h["df_res_filtered"]
    broker_scores    = _h.get("broker_scores", {})
    moonstock_list   = _h.get("moonstock_list", [])

    # ── Upload CSV broker (mode manual, di luar tombol analisa) ──
    if enable_broker and broker_mode == "📁 Upload CSV Manual":
        with st.expander("📁 Upload Broker Summary CSV (Mode Manual)", expanded=not broker_scores):
            uploaded_broker = render_broker_upload_widget()
            if uploaded_broker:
                broker_scores = uploaded_broker
                # Tambahkan kolom ke df_res
                df_res["Broker Score"]    = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("score", 0))
                df_res["Broker Signal"]   = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("signal", "No Data"))
                df_res["Smart Net Lot"]   = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("smart_net_lot", 0))
                df_res["Asing Net Lot"]   = df_res["Kode Saham"].map(lambda t: broker_scores.get(t, {}).get("asing_net_lot", 0))
                df_res["Moonstock Score"] = (
                    (df_res["Broker Score"] >= min_broker_score).astype(int) * 2 +
                    (df_res["Early Momentum Score"] >= 6).astype(int) +
                    (df_res["Silent Score"] >= 5).astype(int) +
                    (df_res["Above MA20"] == "YA").astype(int) +
                    (df_res["Market RS"] == "Outperform").astype(int)
                )
                moonstock_list = df_res[df_res["Moonstock Score"] >= 4]["Kode Saham"].tolist()

    if not df_res.empty:

        # Kolom yang ditampilkan (kondisional Early Momentum Score)
        base_cols = [
            'Kode Saham', 'Free Float (%)', 'MFI (14D)', 'MFI Change 5D',
            'RSI (14)', 'ADX (14)', 'ADX Direction', 'ADX Trend', 'ADX Strength',
            'Divergence Warning', 'PVA', 'Market RS', 'Above MA20', '20D Breakout',
            'Dist to 20D High (%)', 'Last Price', 'Rel Vol (20D)', 'Rel Vol (50D)',
            'Consec Up Days', 'AvgVol20 (Lot)',
        ]
        score_col      = ['Early Momentum Score'] if show_score_in_table else []
        comp_rank_col  = ['Composite Rank', 'Composite Criteria'] if show_composite_rank else []
        watch_col      = ['Pre-Breakout Watch']
        silent_col     = ['Silent Score', 'BB Squeeze', 'OBV Trend', 'Vol Trend Ratio', 'Silent Accum']
        broker_col     = ['Broker Score', 'Broker Signal', 'Smart Net Lot', 'Asing Net Lot'] if (enable_broker and broker_scores) else []
        reason_col     = ['Shortlist Reasons', 'Chart Analysis', 'Visual Chart Analysis']

        all_display_cols = base_cols + score_col + comp_rank_col + watch_col + silent_col + broker_col + reason_col

        # Sort default: Composite Rank DESC, lalu Early Momentum Score DESC
        sort_cols = []
        if show_composite_rank and 'Composite Rank' in df_res.columns:
            sort_cols.append('Composite Rank')
        if show_score_in_table and 'Early Momentum Score' in df_res.columns:
            sort_cols.append('Early Momentum Score')
        if sort_cols:
            df_res_filtered = df_res_filtered.sort_values(sort_cols, ascending=False)

        # ── TAB LAYOUT ──
        has_broker_data = enable_broker and bool(broker_scores)
        tab_labels = [
            "🔥 Shortlist Utama",
            "🔭 Pre-Breakout Watch (Opsi A)",
            "🕵️ Silent Accumulation (v18)",
            "🔍 Semua Hasil Analisa",
        ]
        if has_broker_data:
            tab_labels.append("🌙 Moonstock Radar (v20)")

        tabs = st.tabs(tab_labels)
        tab1 = tabs[0]
        tab2 = tabs[1]
        tab3 = tabs[2]
        tab4 = tabs[3]
        tab5 = tabs[4] if has_broker_data else None

        # ═══════════════════════════════════════
        # TAB 1: SHORTLIST UTAMA
        # ═══════════════════════════════════════
        with tab1:
            st.subheader("🔥 Smart Money Shortlist v16 (Siap Terbang)")
            df_s = (df_res_filtered[df_res_filtered['Kode Saham'].isin(shortlist)]
                    if not df_res_filtered.empty else pd.DataFrame())

            if not df_s.empty:
                cols_s = [c for c in base_cols + score_col + comp_rank_col + reason_col if c in df_s.columns]
                st.dataframe(
                    apply_full_style(df_s[cols_s].style, include_score=show_score_in_table),
                    use_container_width=True
                )

                # ── TradingView Widget ──
                st.markdown("#### 📈 TradingView Chart")
                st.caption("Pilih nama saham dari dropdown untuk melihat chart TradingView langsung di sini.")
                ticker_list_s = df_s['Kode Saham'].tolist()
                # Jaga nilai default jika tv_ticker sudah ada di list ini
                default_idx_s = ticker_list_s.index(st.session_state.tv_ticker) \
                    if st.session_state.tv_ticker in ticker_list_s else 0
                selected_tv_s = st.selectbox(
                    "🔍 Pilih saham untuk chart:", ticker_list_s,
                    index=default_idx_s, key="tv_select_tab1"
                )
                if selected_tv_s:
                    st.session_state.tv_ticker = selected_tv_s
                    chart_mode_s = st.radio(
                        "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                        key="chart_mode_tab1", horizontal=True
                    )
                    if "Plotly" in chart_mode_s:
                        show_plotly_candlestick(selected_tv_s, chart_key=f"plotly_tab1_{selected_tv_s}")
                    else:
                        show_tradingview_widget(selected_tv_s)

                st.markdown("#### 📋 Ringkasan Kandidat Shortlist")
                for _, row in df_s.iterrows():
                    di_icon = "🟢" if row['ADX Direction'] == 'Bullish (DI+>DI-)' else "🔴"
                    score_str = f" | Score: **{int(row['Early Momentum Score'])}**/10" if show_score_in_table else ""
                    st.markdown(
                        f"**{row['Kode Saham']}** | Harga: Rp {row['Last Price']:,} | "
                        f"RSI: {row['RSI (14)']:.1f} | ADX: {row['ADX (14)']:.1f} "
                        f"{di_icon} {row['ADX Direction']} | "
                        f"MFI: {row['MFI (14D)']:.1f} ({row['MFI Change 5D']:+.1f}) | "
                        f"RelVol20: {row['Rel Vol (20D)']:.2f}x{score_str} | "
                        f"*{row['Shortlist Reasons']}*"
                    )
            else:
                st.info("Belum ada kandidat yang memenuhi kriteria super ketat hari ini.")

        # ═══════════════════════════════════════
        # TAB 2: PRE-BREAKOUT WATCH LIST (OPSI A)
        # ═══════════════════════════════════════
        with tab2:
            st.subheader("🔭 Pre-Breakout Watch List (Opsi A)")
            st.markdown("""
> **Filosofi:** Saham ini **BELUM** masuk shortlist utama karena belum breakout / belum consec up / 
> volume belum meledak. Tapi **uang sudah masuk diam-diam** (MFI Change tinggi) dan momentum 
> mulai tumbuh (ADX Rising). *Pantau 1–3 hari ke depan.*
>
> ⚠️ **Risiko lebih tinggi** dari shortlist utama. Sizing lebih kecil, gunakan stop loss ketat.
""")

            if not enable_prebreakout:
                st.warning("Pre-Breakout Watch List dinonaktifkan. Aktifkan di sidebar.")
            else:
                # Ambil dari df_res (belum difilter ketat) agar kandidat pre-breakout tidak tersaring
                df_watch_raw = df_res[df_res['Kode Saham'].isin(prebreakout_list)].copy()

                # Terapkan filter harga & volume saja (filter ketat seperti shortlist tidak berlaku)
                if not df_watch_raw.empty:
                    watch_mask = (
                        (df_watch_raw['Last Price'] >= min_p) &
                        (df_watch_raw['Last Price'] <= max_p) &
                        (df_watch_raw['Free Float (%)'] <= max_ff)
                    )
                    df_watch = df_watch_raw[watch_mask].copy()
                    # Sort by Composite Rank + Early Momentum Score descending
                    sort_w = [c for c in ['Composite Rank', 'Early Momentum Score'] if c in df_watch.columns]
                    if sort_w:
                        df_watch = df_watch.sort_values(sort_w, ascending=False)
                else:
                    df_watch = pd.DataFrame()

                if not df_watch.empty:
                    cols_w = [c for c in base_cols + score_col + comp_rank_col + reason_col if c in df_watch.columns]
                    st.dataframe(
                        apply_full_style(
                            df_watch[cols_w].style,
                            include_score=show_score_in_table
                        ),
                        use_container_width=True
                    )

                    # ── TradingView Widget ──
                    st.markdown("#### 📈 TradingView Chart")
                    st.caption("Pilih nama saham dari dropdown untuk melihat chart TradingView langsung di sini.")
                    ticker_list_w = df_watch['Kode Saham'].tolist()
                    default_idx_w = ticker_list_w.index(st.session_state.tv_ticker) \
                        if st.session_state.tv_ticker in ticker_list_w else 0
                    selected_tv_w = st.selectbox(
                        "🔍 Pilih saham untuk chart:", ticker_list_w,
                        index=default_idx_w, key="tv_select_tab2"
                    )
                    if selected_tv_w:
                        st.session_state.tv_ticker = selected_tv_w
                        chart_mode_w = st.radio(
                            "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                            key="chart_mode_tab2", horizontal=True
                        )
                        if "Plotly" in chart_mode_w:
                            show_plotly_candlestick(selected_tv_w, chart_key=f"plotly_tab2_{selected_tv_w}")
                        else:
                            show_tradingview_widget(selected_tv_w)

                    st.markdown("#### 📋 Ringkasan Pre-Breakout Candidates")
                    for _, row in df_watch.iterrows():
                        sc = int(row['Early Momentum Score'])
                        cr = int(row['Composite Rank']) if 'Composite Rank' in row else 0
                        score_badge = "🟠" if sc >= 6 else "🟡"
                        ff_note = " ⚡Float kecil!" if row['Free Float (%)'] < 15 else ""
                        cr_note = f" | 🔵 Comp Rank: **{cr}**/10" if show_composite_rank else ""
                        st.markdown(
                            f"{score_badge} **{row['Kode Saham']}** | "
                            f"Harga: Rp {row['Last Price']:,} | "
                            f"MFI Change: **{row['MFI Change 5D']:+.1f}** | "
                            f"ADX: {row['ADX (14)']:.0f} ({row['ADX Trend']}) | "
                            f"Consec Up: {row['Consec Up Days']} hari | "
                            f"Rel Vol: {row['Rel Vol (20D)']:.2f}x | "
                            f"Score: **{sc}**/10{cr_note}{ff_note}"
                        )

                    # ── Penjelasan Early Momentum Score breakdown ──
                    with st.expander("📊 Cara Baca Early Momentum Score"):
                        st.markdown("""
| Skor | Komponen | Bobot |
|------|----------|-------|
| +3 | MFI Change 5D ≥ 30 (uang deras masuk) | Tertinggi |
| +2 | MFI Change 5D ≥ 15 (uang masuk sedang) | — |
| +2 | ADX Trend = Rising (momentum baru tumbuh) | Tinggi |
| +2 | Above MA20 (struktur harga masih bullish) | Tinggi |
| +1 | ADX Direction Bullish (DI+ > DI-) | — |
| +1 | Market RS = Outperform vs IHSG | — |
| +1 | RSI 45–70 (zona sehat, belum overbought) | — |
| +1 | Free Float < 15% (float kecil = potensi explosive) | — |
| -2 | Bearish Divergence terdeteksi | Penalti |

**Interpretasi:**
- **8–10**: Sinyal sangat kuat, pantau ketat (tapi sizing kecil)
- **6–7**: Kandidat serius, tunggu konfirmasi volume / candle
- **4–5**: Ada sinyal, tapi masih perlu sabar
- **0–3**: Belum menarik, skip dulu
""")
                else:
                    st.info("Tidak ada kandidat Pre-Breakout Watch hari ini dengan parameter saat ini. "
                            "Coba turunkan 'Min MFI Change 5D untuk Watch' atau 'Min Early Momentum Score' di sidebar.")

        # ═══════════════════════════════════════
        # TAB 3: SILENT ACCUMULATION RADAR (v18)
        # ═══════════════════════════════════════
        with tab3:
            st.subheader("🕵️ Silent Accumulation Radar (v18)")
            st.markdown("""
> **Filosofi:** Menangkap saham seperti **KOTA** — sideways panjang, volume rendah, tapi ada akumulasi
> diam-diam yang terdeteksi dari **Bollinger Band Squeeze + OBV Rising + Vol Trend naik**.
> Screener ini menggunakan filter volume yang jauh lebih rendah dari shortlist utama.
>
> ⚠️ **Ini adalah sinyal paling awal dan paling berisiko.** Tidak ada kepastian kapan bergerak.
> Sizing sangat kecil. Wajib pasang stop loss. Gunakan sebagai watchlist, bukan buy signal langsung.
""")
            if not enable_silent:
                st.warning("Silent Accumulation Radar dinonaktifkan. Aktifkan di sidebar.")
            else:
                df_silent_raw = df_res[df_res['Kode Saham'].isin(silent_list)].copy()

                # Filter harga saja — volume sudah ditangani di logic internal
                if not df_silent_raw.empty:
                    silent_mask = (
                        (df_silent_raw['Last Price'] >= min_p) &
                        (df_silent_raw['Last Price'] <= max_p) &
                        (df_silent_raw['Free Float (%)'] <= max_ff)
                    )
                    if silent_require_squeeze:
                        silent_mask &= df_silent_raw['BB Squeeze'].isin(['SQUEEZE 🔥', 'Sempit'])
                    df_silent = df_silent_raw[silent_mask].copy()
                    df_silent = df_silent.sort_values('Silent Score', ascending=False)
                else:
                    df_silent = pd.DataFrame()

                if not df_silent.empty:
                    # Kolom khusus silent accumulation
                    silent_cols = [
                        'Kode Saham', 'Last Price', 'Free Float (%)', 'AvgVol20 (Lot)',
                        'Composite Rank', 'Silent Score', 'BB Squeeze', 'BB Width (%)', 'OBV Trend',
                        'Vol Trend Ratio', 'Price Tightness (%)',
                        'MFI (14D)', 'MFI Change 5D', 'RSI (14)',
                        'ADX (14)', 'ADX Direction', 'ADX Trend',
                        'Above MA20', 'Dist to 20D High (%)', 'Rel Vol (20D)',
                        'Divergence Warning', 'Market RS', 'Chart Analysis', 'Visual Chart Analysis',
                    ]
                    cols_s = [c for c in silent_cols if c in df_silent.columns]

                    def apply_silent_style(df_styled):
                        styled = (df_styled
                            .map(style_silent_score,  subset=['Silent Score'])
                            .map(style_bb_squeeze,    subset=['BB Squeeze'])
                            .map(style_obv_trend,     subset=['OBV Trend'])
                            .map(style_mfi,           subset=['MFI (14D)'])
                            .map(style_market_rs,     subset=['Market RS'])
                            .map(style_ma_filter,     subset=['Above MA20'])
                            .map(style_adx_trend,     subset=['ADX Trend'])
                            .map(style_adx_dir,       subset=['ADX Direction'])
                            .map(style_divergence,    subset=['Divergence Warning'])
                            .map(style_chart_analysis,subset=['Chart Analysis'])
                            .map(style_visual_chart,  subset=['Visual Chart Analysis'])
                            .format({
                                'Free Float (%)':       '{:.1f}%',
                                'MFI (14D)':            '{:.1f}',
                                'MFI Change 5D':        '{:+.1f}',
                                'RSI (14)':             '{:.1f}',
                                'ADX (14)':             '{:.1f}',
                                'BB Width (%)':         '{:.2f}%',
                                'Vol Trend Ratio':      '{:.2f}x',
                                'Price Tightness (%)':  '{:.2f}%',
                                'Dist to 20D High (%)': '{:.2f}%',
                                'Rel Vol (20D)':        '{:.2f}x',
                            }, na_rep="-")
                        )
                        if 'Composite Rank' in df_styled.data.columns and show_composite_rank:
                            styled = styled.map(style_composite_rank, subset=['Composite Rank'])
                        return styled

                    st.dataframe(
                        apply_silent_style(df_silent[cols_s].style),
                        use_container_width=True,
                        height=420,
                    )

                    # ── TradingView Widget ──
                    st.markdown("#### 📈 TradingView Chart")
                    st.caption("Klik nama saham di dropdown untuk melihat chart.")
                    ticker_list_si = df_silent['Kode Saham'].tolist()
                    default_idx_si = ticker_list_si.index(st.session_state.tv_ticker) \
                        if st.session_state.tv_ticker in ticker_list_si else 0
                    selected_tv_si = st.selectbox(
                        "🔍 Pilih saham untuk chart:", ticker_list_si,
                        index=default_idx_si, key="tv_select_tab3"
                    )
                    if selected_tv_si:
                        st.session_state.tv_ticker = selected_tv_si
                        chart_mode_si = st.radio(
                            "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                            key="chart_mode_tab3", horizontal=True
                        )
                        if "Plotly" in chart_mode_si:
                            show_plotly_candlestick(selected_tv_si, chart_key=f"plotly_tab3_{selected_tv_si}")
                        else:
                            show_tradingview_widget(selected_tv_si)

                    # ── Ringkasan kandidat ──
                    st.markdown("#### 📋 Ringkasan Silent Accumulation Candidates")
                    for _, row in df_silent.iterrows():
                        sc   = int(row['Silent Score'])
                        badge = "🔴" if sc >= 8 else ("🟠" if sc >= 6 else "🟡")
                        sq   = row.get('BB Squeeze', 'Normal')
                        obv  = row.get('OBV Trend', '-')
                        vtr  = row.get('Vol Trend Ratio', 1.0)
                        pt   = row.get('Price Tightness (%)', 0.0)
                        ff_note = " ⚡Float kecil!" if row['Free Float (%)'] < 15 else ""
                        st.markdown(
                            f"{badge} **{row['Kode Saham']}** | "
                            f"Rp {row['Last Price']:,} | "
                            f"AvgVol: {int(row['AvgVol20 (Lot)']):,} lot | "
                            f"Silent Score: **{sc}**/10 | "
                            f"BB: **{sq}** | OBV: **{obv}** | "
                            f"Vol Trend: {vtr:.2f}x | Price Tightness: {pt:.1f}%"
                            f"{ff_note}"
                        )

                    # ── Cara baca ──
                    with st.expander("📖 Cara Baca Silent Accumulation Score & Indikator"):
                        st.markdown("""
**Silent Accumulation Score (0–10)** — Mendeteksi akumulasi sebelum harga bergerak:

| Skor | Komponen | Keterangan |
|------|----------|------------|
| +3 | BB Squeeze 🔥 | Bollinger Band dalam 10% tersempit selama 50 hari → energi terkompresi |
| +1 | BB Sempit | BB dalam 25% tersempit → mulai menyempit |
| +2 | OBV Rising ↑ | On-Balance Volume naik → volume beli > jual secara kumulatif |
| +2 | Vol Trend Ratio ≥ 1.3 | Volume 5D rata-rata > 130% dari rata-rata 20D → volume diam-diam naik |
| +1 | Vol Trend Ratio ≥ 1.1 | Volume mulai sedikit di atas rata-rata |
| +1 | Price Tightness < 3% | Harga bergerak sangat sempit = akumulasi terselubung |
| +1 | MFI Change > 0 | Uang mulai masuk walau sedikit |
| +1 | ADX Rising | Momentum mulai tumbuh |
| +1 | ADX Bullish | DI+ > DI- |
| +1 | Free Float < 15% | Float kecil = lebih explosive saat naik |
| -2 | Bearish Divergence | Sinyal peringatan |
| -1 | RSI > 70 | Sudah overbought, terlambat |
| -1 | Below MA20 | Struktur harga bearish |

**Interpretasi:**
- **8–10** 🔴 Sinyal sangat kuat — pantau harian, siapkan beli saat ada candle konfirmasi + volume spike
- **6–7** 🟠 Kandidat serius — masukkan watchlist, alert di harga resistance terdekat
- **4–5** 🟡 Ada potensi tapi masih sangat awal — pantau mingguan
- **0–3** Belum menarik

**Tips konfirmasi entry:**
Jangan beli hanya dari skor ini. Tunggu salah satu dari: candle bullish kuat + volume 2x rata-rata, atau breakout dari range sideways dengan volume besar.
""")
                else:
                    st.info(
                        "Tidak ada kandidat Silent Accumulation hari ini. "
                        "Coba turunkan 'Min Silent Accumulation Score' atau 'Min Avg Vol untuk Silent' di sidebar."
                    )

        # ═══════════════════════════════════════
        # TAB 4: SEMUA HASIL ANALISA
        # ═══════════════════════════════════════
        with tab4:
            st.subheader("🔍 Seluruh Hasil Analisa")

            # Sort option
            sort_options = ['Composite Rank', 'Early Momentum Score', 'Silent Score', 'MFI Change 5D', 'MFI (14D)', 'Rel Vol (20D)', 'ADX (14)']
            sort_col = st.selectbox(
                "Urutkan berdasarkan:",
                options=sort_options,
                index=0
            )
            df_sorted = (df_res_filtered.sort_values(sort_col, ascending=False)
                         if not df_res_filtered.empty and sort_col in df_res_filtered.columns
                         else df_res_filtered)

            if not df_sorted.empty:
                cols_all = [c for c in all_display_cols if c in df_sorted.columns]
                st.dataframe(
                    apply_full_style(
                        df_sorted[cols_all].style,
                        include_score=show_score_in_table,
                        include_watch=True,
                        include_silent=True,
                    ),
                    use_container_width=True,
                    height=500
                )

                # ── TradingView Widget ──
                st.markdown("#### 📈 TradingView Chart")
                st.caption("Pilih nama saham dari dropdown untuk melihat chart TradingView langsung di sini.")
                ticker_list_all = df_sorted['Kode Saham'].tolist()
                default_idx_all = ticker_list_all.index(st.session_state.tv_ticker) \
                    if st.session_state.tv_ticker in ticker_list_all else 0
                selected_tv_all = st.selectbox(
                    "🔍 Pilih saham untuk chart:", ticker_list_all,
                    index=default_idx_all, key="tv_select_tab4"
                )
                if selected_tv_all:
                    st.session_state.tv_ticker = selected_tv_all
                    chart_mode_all = st.radio(
                        "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                        key="chart_mode_tab4", horizontal=True
                    )
                    if "Plotly" in chart_mode_all:
                        show_plotly_candlestick(selected_tv_all, chart_key=f"plotly_tab4_{selected_tv_all}")
                    else:
                        show_tradingview_widget(selected_tv_all)
            else:
                st.info("Tidak ada data yang memenuhi filter.")

        # ═══════════════════════════════════════
        # TAB 5: MOONSTOCK RADAR (v20)
        # ═══════════════════════════════════════
        if tab5 is not None:
            with tab5:
                st.subheader("🌙 Moonstock Radar (v20) — 5 Kriteria Terbaik")
                st.markdown("""
> **Filosofi Moonstock:** Saham terbaik adalah yang memenuhi **semua 5 kriteria sekaligus**:
> Smart money mengakumulasi (Broker Score), uang sudah masuk (Early Momentum), 
> akumulasi diam-diam (Silent Score), di atas MA20 (struktur bullish), dan mengungguli IHSG (Market RS).
>
> 💡 Skor 5/5 = kandidat prioritas tertinggi. Skor 4/5 = kandidat kuat. Di bawah 4 = belum saatnya.
""")

                # Upload CSV mode: tampilkan widget di sini jika belum ada data
                if broker_mode == "📁 Upload CSV Manual" and not broker_scores:
                    st.info("Upload file CSV broker di expander di atas untuk mengaktifkan Moonstock Radar.")
                elif not broker_scores:
                    st.warning("Broker data belum tersedia. Jalankan analisa dengan Broker Summary diaktifkan.")
                else:
                    # Filter moonstock candidates
                    df_moon_all = df_res[df_res['Kode Saham'].isin(moonstock_list)].copy()
                    if not df_moon_all.empty and 'Moonstock Score' in df_moon_all.columns:
                        df_moon_all = df_moon_all.sort_values('Moonstock Score', ascending=False)

                    if not df_moon_all.empty:
                        # Tabel ringkas
                        moon_display_cols = [
                            'Kode Saham', 'Moonstock Score', 'Last Price', 'Free Float (%)',
                            'Broker Score', 'Broker Signal', 'Smart Net Lot', 'Asing Net Lot',
                            'Early Momentum Score', 'Silent Score', 'Above MA20', 'Market RS',
                            'MFI (14D)', 'MFI Change 5D', 'ADX (14)', 'ADX Trend',
                            'Composite Rank', 'Chart Analysis',
                        ]
                        moon_cols = [c for c in moon_display_cols if c in df_moon_all.columns]

                        def style_moonstock_score(val):
                            try:
                                n = float(val)
                                if n >= 5: return 'background-color: #c0392b; color: white; font-weight: bold'
                                if n >= 4: return 'background-color: #e67e22; color: white; font-weight: bold'
                            except:
                                pass
                            return ''

                        moon_styled = df_moon_all[moon_cols].style
                        if 'Moonstock Score' in moon_cols:
                            moon_styled = moon_styled.map(style_moonstock_score, subset=['Moonstock Score'])
                        if True:
                            if 'Broker Score' in moon_cols:
                                moon_styled = moon_styled.map(style_broker_score, subset=['Broker Score'])
                            if 'Broker Signal' in moon_cols:
                                moon_styled = moon_styled.map(style_broker_signal, subset=['Broker Signal'])
                        if 'Early Momentum Score' in moon_cols:
                            moon_styled = moon_styled.map(style_early_momentum, subset=['Early Momentum Score'])
                        if 'Silent Score' in moon_cols:
                            moon_styled = moon_styled.map(style_silent_score, subset=['Silent Score'])
                        if 'Market RS' in moon_cols:
                            moon_styled = moon_styled.map(style_market_rs, subset=['Market RS'])
                        if 'Above MA20' in moon_cols:
                            moon_styled = moon_styled.map(style_ma_filter, subset=['Above MA20'])
                        if 'Chart Analysis' in moon_cols:
                            moon_styled = moon_styled.map(style_chart_analysis, subset=['Chart Analysis'])
                        if 'Composite Rank' in moon_cols and show_composite_rank:
                            moon_styled = moon_styled.map(style_composite_rank, subset=['Composite Rank'])
                        moon_styled = moon_styled.format({
                            'Free Float (%)': '{:.1f}%',
                            'MFI (14D)': '{:.1f}',
                            'MFI Change 5D': '{:+.1f}',
                            'ADX (14)': '{:.1f}',
                        }, na_rep='-')

                        st.dataframe(moon_styled, use_container_width=True)

                        # Detail per saham
                        st.markdown("#### 📋 Detail Broker Analysis per Kandidat")
                        for _, row in df_moon_all.iterrows():
                            ticker = row['Kode Saham']
                            ms = int(row.get('Moonstock Score', 0))
                            bs = int(row.get('Broker Score', 0))
                            badge = "🔴" if ms >= 5 else "🟠"
                            with st.expander(f"{badge} {ticker} — Moonstock Score: {ms}/5 | Broker Score: {bs}/10"):
                                if ticker in broker_scores:
                                    render_broker_detail_tab(ticker, broker_scores[ticker])
                                else:
                                    st.info("Data broker tidak tersedia untuk saham ini.")

                                # Chart
                                chart_mode_moon = st.radio(
                                    "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                                    key=f"chart_mode_moon_{ticker}", horizontal=True
                                )
                                if "Plotly" in chart_mode_moon:
                                    show_plotly_candlestick(ticker, chart_key=f"plotly_moon_{ticker}")
                                else:
                                    show_tradingview_widget(ticker)

                        # Penjelasan kriteria
                        with st.expander("📖 Cara Baca Moonstock Score"):
                            st.markdown("""
| Kriteria | Bobot | Kondisi |
|---|---|---|
| **Broker Score** | ×2 (maks 2) | ≥ Min Broker Score (sidebar) |
| **Early Momentum Score** | ×1 | ≥ 6 |
| **Silent Score** | ×1 | ≥ 5 |
| **Above MA20** | ×1 | YA |
| **Market RS** | ×1 | Outperform |

**Interpretasi:**
- **5/5** 🔴 Semua kriteria terpenuhi — kandidat prioritas tertinggi
- **4/5** 🟠 Hampir sempurna — kandidat kuat, tunggu konfirmasi volume
- **< 4** Belum memenuhi syarat Moonstock

**Catatan:** Moonstock Score hanya valid jika data broker tersedia. Broker Score yang tinggi mengindikasikan smart money sedang mengakumulasi secara aktif.
""")
                    else:
                        st.info(
                            "Belum ada kandidat Moonstock hari ini. "
                            "Coba turunkan 'Min Broker Score untuk Moonstock' di sidebar, "
                            "atau jalankan analisa dengan lebih banyak saham."
                        )

        # ── AI Chart Analysis ──
        st.markdown("---")
        st.subheader("🤖 AI Chart Analysis (On-Demand)")
        st.caption(
            "Klik tombol di bawah untuk analisa chart saham tertentu. "
            "Claude akan melihat chart Yahoo Finance + data OHLCV 30 hari terakhir."
        )

        # Inisialisasi session_state untuk menyimpan hasil agar tidak hilang saat rerun
        if "ai_results" not in st.session_state:
            st.session_state.ai_results = {}   # dict: ticker -> result dict
        if "ai_screenshot" not in st.session_state:
            st.session_state.ai_screenshot = {}  # dict: ticker -> png bytes

        LABEL_COLOR = {
            "Overextended 🚨":       "#ff4b4b",
            "Breakout Valid 🚀":      "#1a8c1a",
            "Pullback Healthy 👍":    "#2196F3",
            "Uptrend Normal":         "#4CAF50",
            "Downtrend ❌":            "#cc0000",
            "Sideways / Konsolidasi": "#888888",
        }

        if not df_res.empty:
            # Prioritaskan shortlist + prebreakout + silent di dropdown AI
            priority       = shortlist + [k for k in prebreakout_list if k not in shortlist]
            priority      += [k for k in silent_list if k not in priority]
            rest           = [k for k in sorted(df_res['Kode Saham'].tolist()) if k not in priority]
            ticker_options = priority + rest

            col_sel, col_btn = st.columns([3, 1])
            with col_sel:
                selected_for_ai = st.selectbox(
                    "Pilih saham untuk dianalisa:", ticker_options,
                    key="ai_chart_select"
                )
            with col_btn:
                st.write("")
                run_ai = st.button("🔍 Analisa Chart", type="primary", key="run_ai_btn")

            # Tombol diklik → jalankan analisa, simpan ke session_state
            if run_ai and selected_for_ai:
                with st.spinner(f"Claude sedang analisa chart {selected_for_ai}…"):
                    result   = ai_chart_analysis(selected_for_ai)
                    png_bytes = screenshot_yahoo_chart(selected_for_ai + ".JK")
                st.session_state.ai_results[selected_for_ai]    = result
                st.session_state.ai_screenshot[selected_for_ai] = png_bytes

            # Render hasil dari session_state (tetap tampil meski page rerun)
            if selected_for_ai in st.session_state.ai_results:
                result = st.session_state.ai_results[selected_for_ai]
                label  = result["label"]
                reason = result["reasoning"]
                has_ss = result["has_screenshot"]
                color  = next((v for k, v in LABEL_COLOR.items() if k in label), "#888888")

                st.markdown(
                    f"### {selected_for_ai} &nbsp; "
                    f'<span style="background:{color};color:white;'
                    f'padding:4px 14px;border-radius:20px;font-size:1em;">'
                    f"{label}</span>",
                    unsafe_allow_html=True
                )
                st.markdown(f"**Analisa:** {reason}")

                src_note = "📸 Screenshot Yahoo Finance + data OHLCV" if has_ss else "📊 Data OHLCV saja (screenshot gagal)"
                st.caption(
                    f"Sumber: {src_note} · "
                    f"[Lihat chart Yahoo Finance ↗](https://finance.yahoo.com/quote/{selected_for_ai}.JK/)"
                )

                png_bytes = st.session_state.ai_screenshot.get(selected_for_ai)
                if png_bytes:
                    with st.expander("📷 Screenshot Chart Yahoo Finance"):
                        st.image(png_bytes, use_container_width=True)

            # Riwayat analisa sesi ini
            done = [k for k in ticker_options if k in st.session_state.ai_results]
            if len(done) > 1:
                with st.expander(f"📋 Riwayat analisa sesi ini ({len(done)} saham)"):
                    for tk in done:
                        r  = st.session_state.ai_results[tk]
                        c2 = next((v for k, v in LABEL_COLOR.items() if k in r["label"]), "#888888")
                        st.markdown(
                            f'**{tk}** — <span style="background:{c2};color:white;'
                            f'padding:2px 10px;border-radius:12px;font-size:0.85em;">'
                            f'{r["label"]}</span> &nbsp; {r["reasoning"]}',
                            unsafe_allow_html=True
                        )

        # ── Download ──
        df_s_dl    = df_res[df_res['Kode Saham'].isin(shortlist)] if not df_res.empty else pd.DataFrame()
        df_w_dl    = df_res[df_res['Kode Saham'].isin(prebreakout_list)] if not df_res.empty else pd.DataFrame()
        df_si_dl   = df_res[df_res['Kode Saham'].isin(silent_list)] if not df_res.empty else pd.DataFrame()

        def to_excel_report_v18(df_short, df_watch, df_silent, df_all):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_short.to_excel(writer, index=False, sheet_name='Shortlist')
                if not df_watch.empty:
                    df_watch.to_excel(writer, index=False, sheet_name='Pre-Breakout Watch')
                if not df_silent.empty:
                    df_silent.to_excel(writer, index=False, sheet_name='Silent Accumulation')
                df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
            return output.getvalue()

        def to_excel_report_v20(df_short, df_watch, df_silent, df_all, df_moon=None):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_short.to_excel(writer, index=False, sheet_name='Shortlist')
                if not df_watch.empty:
                    df_watch.to_excel(writer, index=False, sheet_name='Pre-Breakout Watch')
                if not df_silent.empty:
                    df_silent.to_excel(writer, index=False, sheet_name='Silent Accumulation')
                if df_moon is not None and not df_moon.empty:
                    df_moon.to_excel(writer, index=False, sheet_name='Moonstock Radar')
                df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
            return output.getvalue()

        df_moon_dl = df_res[df_res['Kode Saham'].isin(moonstock_list)] if moonstock_list and not df_res.empty else pd.DataFrame()
        excel_data = to_excel_report_v20(df_s_dl, df_w_dl, df_si_dl, df_res_filtered, df_moon_dl)
        st.sidebar.download_button(
            label="📥 Download Report Excel v20",
            data=excel_data,
            file_name=f"Analisa_BEI_{date.today()}_v20.xlsx",
            mime="application/vnd.ms-excel"
        )

        # ── Legenda ──
        with st.expander("📖 Legenda Indikator v20"):
            st.markdown("""
| Kolom | Penjelasan |
|---|---|
| **MFI (14D)** | Money Flow Index 14 hari. > 80 = overbought (merah), < 40 = oversold (hijau) |
| **MFI Change 5D** | Perubahan MFI dalam 5 hari terakhir. Positif = uang masuk |
| **RSI (14)** | Relative Strength Index. Ideal entry: 40–70 |
| **ADX (14)** | Kekuatan tren. > 25 = tren kuat (biru) |
| **ADX Direction** | **DI+ > DI-** = tren naik. **DI- > DI+** = tren turun |
| **ADX Trend** | Apakah kekuatan ADX sedang Rising/Falling/Flat |
| **ADX Strength** | Weak / Moderate / Strong / Very Strong |
| **Divergence Warning** | Harga buat higher high tapi MFI lower high = potensi reversal |
| **PVA** | Price Volume Analysis: konfirmasi volume terhadap arah harga |
| **Market RS** | Kinerja saham vs IHSG 20 hari terakhir |
| **Rel Vol (20D)** | Volume hari ini vs rata-rata 20 hari |
| **Rel Vol (50D)** | Volume hari ini vs rata-rata 50 hari |
| **Chart Analysis** | `Overextended 🚨` · `Breakout Valid 🚀` · `Pullback Healthy 👍` · `Uptrend Normal` · `Downtrend ❌` · `Sideways` |
| **Visual Chart Analysis** 🆕 | Rule-based analisa visual: Candlestick pattern + Vol Climax + Consolidation Breakout + Trendline Slope + Jarak ke Resistance |
| **Early Momentum Score** | Skor 0–10 sinyal awal: MFI Change + ADX Rising + MA20 + RSI + Float. ≥6 = menarik |
| **Pre-Breakout Watch** | `🔭 Watch` = sinyal akumulasi awal tapi belum breakout. Pantau 1–3 hari ke depan |
| **Silent Score** 🆕 | Skor 0–10 deteksi akumulasi diam-diam: BB Squeeze + OBV + Vol Trend. ≥6 = kandidat |
| **BB Squeeze** 🆕 | `SQUEEZE 🔥` = BB sangat sempit (10% tersempit 50 hari). Energi terkompresi, siap meledak |
| **OBV Trend** 🆕 | Tren On-Balance Volume. `Rising ↑` = akumulasi tersembunyi terdeteksi |
| **Vol Trend Ratio** 🆕 | Rata-rata volume 5D / rata-rata 20D. > 1.2 = volume mulai diam-diam naik |
| **Price Tightness (%)** 🆕 | Koefisien variasi harga 10 hari. < 3% = harga sideways sangat ketat = akumulasi |
| **Silent Accum** 🆕 | `🕵️ Silent` = kandidat Silent Accumulation (pola pre-KOTA) |
| **Composite Rank** 🆕 | Skor 0–10 gabungan untuk prioritas entry: ADX kuat (>50) + Tightness <3% + Vol Trend >2x + Float <20% + OBV Rising + Dekat Resistance. **≥8 = prioritas tertinggi**. Warna biru makin gelap = makin kuat |
| **Composite Criteria** 🆕 | Detail kriteria yang terpenuhi untuk Composite Rank masing-masing saham |
| **Broker Score** 🆕 | Skor 0–10 analisa broker summary. ≥8 = Akumulasi Kuat, ≥6 = Akumulasi, <4 = Distribusi |
| **Broker Signal** 🆕 | Label sinyal broker: Akumulasi Kuat / Akumulasi / Netral / Distribusi / Distribusi Kuat |
| **Smart Net Lot** 🆕 | Net lot pembelian broker smart money (institusi/asing) dalam periode Broker Summary |
| **Asing Net Lot** 🆕 | Net lot pembelian broker asing (ES, HD, AK, ZP, BK, AI, AZ, RX, YJ) |
| **Moonstock Score** 🆕 | Skor 0–5 gabungan 5 kriteria. **5/5** = prioritas tertinggi (semua sinyal hijau) |

**Visual Chart Analysis — Detail Pola:**
| Pola | Keterangan |
|---|---|
| Doji | Body sangat kecil (< 10% range candle) — pasar ragu |
| Hammer 🔨 | Lower shadow ≥ 2× body, di zona support — sinyal reversal bullish |
| Bullish Engulfing 🟢 | Candle bullish besar menelan candle bearish sebelumnya |
| Bearish Engulfing 🔴 | Candle bearish besar menelan candle bullish sebelumnya |
| Shooting Star ⭐ | Upper shadow panjang di zona resistance — sinyal reversal bearish |
| Vol Climax 💥 | Volume hari ini > 3× rata-rata 20 hari — sinyal kekuatan ekstremal |
| Consol Breakout 🚀 | Harga keluar dari range sempit (CV < 3%) 10 hari terakhir |
| Trend:Up ↗ / Down ↘ | Slope linear regression harga 20 hari (arah tren jangka pendek) |
| Dekat R(x%) | Jarak ke resistance 20D < 2% — tinggal sedikit lagi untuk breakout |
| Menuju R(x%) | Jarak ke resistance 20D antara 2–5% |
""")

else:
    st.info(
        f"📂 Database: **{loaded_file}**\n\n"
        "**Perubahan utama v20:**\n"
        "- 🆕 **Broker Summary Analysis**: Smart Money vs Retail tracking berdasarkan data RTI Business\n"
        "- 🆕 **Broker Score 0–10**: Net buy smart money, rasio asing, pola distribusi broker\n"
        "- 🆕 **Tab Moonstock Radar**: Gabungan 5 kriteria — Broker + Early Momentum + Silent + MA20 + Market RS\n"
        "- ✅ Semua fitur v19 dipertahankan (Visual Chart Analysis, Plotly Candlestick, Silent Accumulation, AI Chart Analysis)"
    )
