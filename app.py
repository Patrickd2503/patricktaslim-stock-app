import streamlit as st
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

# ─────────────────────────────────────────────
# SETUP (jalankan sekali sebelum app pertama kali):
#   pip install playwright
#   playwright install chromium
# ─────────────────────────────────────────────

# --- CONFIG DASHBOARD ---
st.set_page_config(page_title="Monitor Saham BEI v15", layout="wide")
st.title("🚀 Dashboard Akumulasi: Smart Money Monitor v15 – AI Chart Analysis")

st.markdown("""
**Update v15:**
- ✅ ADX sekarang pakai **DI+ vs DI-** (arah tren benar-benar bullish)
- ✅ **Bearish Divergence** otomatis tolak dari Shortlist
- ✅ ADX Trend **Falling** tidak masuk shortlist
- ✅ MFI threshold konsisten
- ✅ Relative Volume dibandingkan **50D** juga (bukan hanya 20D)
- ✅ Kolom **ADX Strength** & **ADX Trend** tetap ditampilkan
- 🆕 **AI Chart Analysis** — klik tombol per saham, Claude analisa chart Yahoo Finance + OHLCV data
""")

# ─────────────────────────────────────────────
# 1. CACHE DATA
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    # Ambil lebih panjang agar rolling 50D tidak NaN
    extended_start = start_date - timedelta(days=500)
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_date,
                         threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            return df['Close'], df['Volume'], df['High'], df['Low']
        else:
            return df[['Close']], df[['Volume']], df[['High']], df[['Low']]
    except Exception as e:
        st.error(f"Error download data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

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
    """Styling untuk DI Direction (Bullish/Bearish)"""
    if val == 'Bullish (DI+>DI-)': return 'color: #006400; font-weight: bold;'
    if val == 'Bearish (DI->DI+)': return 'color: #cc0000; font-weight: bold;'
    return ''

def style_chart_analysis(val):
    """Styling untuk kolom Chart Analysis"""
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

# ─────────────────────────────────────────────
# 4. EXPORT EXCEL
# ─────────────────────────────────────────────
def to_excel_report(df_short, df_all):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_short.to_excel(writer, index=False, sheet_name='Shortlist')
        df_all.to_excel(writer, index=False, sheet_name='Semua Analisa')
    return output.getvalue()

# ─────────────────────────────────────────────
# 5. FUNGSI BEARISH DIVERGENCE DETECTION
# ─────────────────────────────────────────────
def detect_bearish_divergence(close: pd.Series, mfi_series: pd.Series, window: int = 10) -> bool:
    """
    Deteksi bearish divergence: harga bikin higher high tapi MFI bikin lower high
    dalam window N candle terakhir.
    """
    if len(close) < window + 1 or len(mfi_series) < window + 1:
        return False

    c_window = close.iloc[-window:]
    m_window = mfi_series.iloc[-window:]

    # Cari dua swing high di harga
    c_max_idx = c_window.idxmax()
    c_prev = c_window[c_window.index < c_max_idx]
    if c_prev.empty:
        return False
    c_prev_max = c_prev.max()

    # Apakah harga bikin higher high?
    price_hh = c_window[c_max_idx] > c_prev_max

    # Cek MFI di titik yang sama
    m_at_c_max = m_window.loc[c_max_idx] if c_max_idx in m_window.index else m_window.iloc[-1]
    m_prev_idx = c_prev.idxmax()
    m_at_prev = m_window.loc[m_prev_idx] if m_prev_idx in m_window.index else m_window.iloc[0]

    # MFI bikin lower high saat harga higher high = bearish divergence
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
    """
    Mengembalikan label Chart Analysis berdasarkan kondisi teknikal:
      - Overextended 🚨   : terlalu jauh dari MA20
      - Breakout Valid 🚀  : breakout sehat
      - Pullback Healthy 👍: retrace ke MA20 (entry bagus)
      - Uptrend Normal     : tren naik biasa
      - Downtrend ❌        : tren turun, hindari
      - Sideways / Konsolidasi : belum jelas arahnya
    """
    last_price = float(close.iloc[-1])

    # Hitung jarak harga ke MA20 dalam %
    dist_to_ma20_pct = ((last_price - ma20) / ma20 * 100) if ma20 > 0 else 0.0

    # --- Overextended: harga sudah >10% di atas MA20 DAN RSI tinggi ---
    if dist_to_ma20_pct > 10 and last_rsi > 70:
        return "Overextended 🚨"

    # --- Downtrend: harga di bawah MA20, ADX kuat bearish ---
    if last_price < ma20 and not is_adx_bullish and last_adx > 20:
        return "Downtrend ❌"

    # --- Breakout Valid: baru breakout, volume mendukung, tidak overextended ---
    if (is_breakout == "YA"
            and rel_vol >= 1.5
            and is_adx_bullish
            and dist_to_ma20_pct <= 10
            and p_change_today > 0):
        return "Breakout Valid 🚀"

    # --- Pullback Healthy: di atas MA20 tapi retrace ke dekat MA20 (0%–5%) ---
    if (last_price >= ma20
            and 0 <= dist_to_ma20_pct <= 5
            and is_adx_bullish
            and mfi_change_5d > 0):
        return "Pullback Healthy 👍"

    # --- Uptrend Normal: di atas MA20, ADX bullish, tidak overextended ---
    if last_price > ma20 and is_adx_bullish and dist_to_ma20_pct <= 10:
        return "Uptrend Normal"

    # --- Sideways / Konsolidasi: ADX lemah, tidak ada arah jelas ---
    return "Sideways / Konsolidasi"


# ─────────────────────────────────────────────
# 6. FUNGSI ANALISA UTAMA v13
# ─────────────────────────────────────────────
def get_signals_and_data(df_c, df_v, df_h, df_l, df_ref, min_vol_lot):
    results = []
    shortlist_keys = []
    min_vol_lembar = min_vol_lot * 100
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

        if len(c) < 55:  # minimal 55 hari agar rolling50D tidak NaN
            continue

        # ── Volume filter ──
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        avg_vol50 = v.rolling(50).mean().iloc[-1]   # FIX: tambahan 50D baseline
        if avg_vol20 < min_vol_lembar:
            continue

        rel_vol_20 = v.iloc[-1] / avg_vol20 if avg_vol20 > 0 else 0.0
        rel_vol_50 = v.iloc[-1] / avg_vol50 if avg_vol50 > 0 else 0.0
        # Pakai yang lebih konservatif untuk menghindari false spike
        rel_vol = min(rel_vol_20, rel_vol_50 * 1.2)  # weighted blend

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

        # ── ADX + DI+ / DI- (FIX UTAMA v13) ──
        adx_df = pta.adx(high=h, low=l, close=c, length=14)
        if adx_df is not None and not adx_df.empty:
            last_adx = float(adx_df['ADX_14'].iloc[-1])
            last_dmp  = float(adx_df['DMP_14'].iloc[-1])   # DI+
            last_dmn  = float(adx_df['DMN_14'].iloc[-1])   # DI-

            # Arah tren berdasarkan DI
            adx_direction = "Bullish (DI+>DI-)" if last_dmp > last_dmn else "Bearish (DI->DI+)"
            is_adx_bullish = last_dmp > last_dmn  # FIX: kunci baru

            # Trend ADX (apakah ADX sedang naik atau turun?)
            adx_prev3 = adx_df['ADX_14'].iloc[-4:-1].mean()
            if last_adx > adx_prev3 + 0.5:
                adx_trend = "Rising"
            elif last_adx < adx_prev3 - 0.5:
                adx_trend = "Falling"
            else:
                adx_trend = "Flat"

            # Kekuatan ADX
            if last_adx >= 40:   adx_strength = "Very Strong"
            elif last_adx >= 25: adx_strength = "Strong"
            elif last_adx >= 20: adx_strength = "Moderate"
            else:                adx_strength = "Weak"
        else:
            last_adx      = 0.0
            last_dmp      = 0.0
            last_dmn      = 0.0
            adx_direction = "N/A"
            adx_trend     = "N/A"
            adx_strength  = "N/A"
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

        # ── Bearish Divergence (FIX v13) ──
        has_bearish_div = detect_bearish_divergence(c, mfi_series, window=10)
        divergence_warning = "⚠️ Bearish Divergence" if has_bearish_div else ""

        # ── CHART ANALYSIS ──
        chart_analysis = get_chart_analysis(
            close=c,
            ma20=ma20,
            last_rsi=last_rsi,
            last_adx=last_adx,
            is_adx_bullish=is_adx_bullish,
            is_breakout=is_breakout,
            dist_20high=dist_20high,
            mfi_change_5d=mfi_change_5d,
            p_change_today=p_change_today,
            rel_vol=rel_vol,
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
            # FIX: tambah syarat is_adx_bullish
            reasons.append("Strong Trend + MFI Rising (DI+>DI-)")
        if is_above_ma20 == "YA" and last_rsi < 75 and is_breakout == "YA":
            reasons.append("Above MA20 + Breakout")

        # ── SHORTLIST LOGIC v13 (lebih ketat) ──
        is_shortlist = (
            len(reasons) >= 3
            and rs == "Outperform"
            and is_above_ma20 == "YA"
            and last_mfi >= 55          # FIX: konsisten, harus ada money flow masuk
            and last_mfi < 85           # FIX: tidak overbought ekstrem
            and last_adx > 22
            and is_adx_bullish          # FIX: DI+ harus > DI-
            and adx_trend != "Falling"  # FIX: ADX tidak boleh dalam tren melemah
            and not has_bearish_div     # FIX: tolak jika ada bearish divergence
        )

        if is_shortlist:
            shortlist_keys.append(ticker_name)

        results.append({
            'Kode Saham':         ticker_name,
            'Free Float (%)':     float(ff_lookup.get(ticker_name, 0.0)),
            'MFI (14D)':          float(last_mfi),
            'MFI Change 5D':      float(mfi_change_5d),
            'RSI (14)':           float(last_rsi),
            'ADX (14)':           float(last_adx),
            'ADX Direction':      adx_direction,   # KOLOM BARU
            'ADX Trend':          adx_trend,
            'ADX Strength':       adx_strength,
            'Divergence Warning': divergence_warning,
            'PVA':                pva,
            'Market RS':          rs,
            'Above MA20':         is_above_ma20,
            '20D Breakout':       is_breakout,
            'Dist to 20D High (%)': dist_20high,
            'Last Price':         int(round(c.iloc[-1])),
            'Rel Vol (20D)':      float(rel_vol_20),
            'Rel Vol (50D)':      float(rel_vol_50),  # KOLOM BARU
            'Consec Up Days':     consecutive_up,
            'AvgVol20 (Lot)':     int(avg_vol20 / 100),
            'Shortlist Reasons':  ", ".join(reasons) if reasons else "",
            'Chart Analysis':     chart_analysis,
        })

    df_results = pd.DataFrame(results)
    return df_results, shortlist_keys

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
    """
    Ambil screenshot chart Yahoo Finance via Playwright headless.
    Return PNG bytes, atau None jika gagal.
    """
    try:
        from playwright.sync_api import sync_playwright
        url = f"https://finance.yahoo.com/quote/{ticker_jk}/"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Tutup consent popup jika ada
            try:
                page.click('button:has-text("Accept")', timeout=3000)
            except Exception:
                pass
            try:
                page.click('button:has-text("Reject all")', timeout=2000)
            except Exception:
                pass
            # Tunggu chart container muncul
            try:
                page.wait_for_selector('canvas, [data-testid="chart-container"]', timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            # Crop area chart saja (atas: y=140, tinggi 400px)
            png = page.screenshot(clip={"x": 0, "y": 140, "width": 1280, "height": 420})
            browser.close()
            return png
    except Exception as e:
        return None


@st.cache_data(ttl=1800)
def fetch_ohlcv_summary(ticker_jk: str) -> str:
    """
    Ambil 60 hari OHLCV terakhir dari yfinance, return ringkasan teks untuk Claude.
    """
    try:
        df = yf.download(ticker_jk, period="90d", progress=False, auto_adjust=True)
        if df.empty:
            return "Data OHLCV tidak tersedia."
        df = df.tail(60)
        # Hitung MA20, MA50
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
    """
    Gabungkan screenshot Yahoo Finance + data OHLCV,
    kirim ke Claude API, kembalikan dict:
      { 'label': str, 'reasoning': str, 'has_screenshot': bool }
    """
    ticker_jk = ticker_code + ".JK"

    # 1. Data OHLCV teks
    ohlcv_text = fetch_ohlcv_summary(ticker_jk)

    # 2. Screenshot chart Yahoo Finance
    png_bytes = screenshot_yahoo_chart(ticker_jk)
    has_screenshot = png_bytes is not None

    # 3. Susun pesan ke Claude
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
        # Strip markdown fences jika ada
        clean = raw_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        label = parsed.get("label", "Sideways / Konsolidasi")
        # Validasi label
        if not any(lb in label for lb in CHART_LABELS):
            label = "Sideways / Konsolidasi"
        return {
            "label": label,
            "reasoning": parsed.get("reasoning", ""),
            "has_screenshot": has_screenshot,
        }
    except Exception as e:
        return {
            "label": "Sideways / Konsolidasi",
            "reasoning": f"Error analisa: {e}",
            "has_screenshot": has_screenshot,
        }


# ─────────────────────────────────────────────
# 7. SIDEBAR
# ─────────────────────────────────────────────
st.sidebar.header("⚙️ Konfigurasi v15")

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect(
    "Pilih Saham (Kosongkan = Semua):", options=target_list)

min_p       = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p       = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=100000)
max_ff      = float(st.sidebar.slider("Maximal Free Float (%)", 0.0, 100.0, 100.0))

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Filter Siap Terbang")
min_mfi_change   = st.sidebar.number_input("Min MFI Change 5D", value=8.0, step=0.5)
min_adx          = st.sidebar.number_input("Min ADX (14)", value=22, step=1)
only_outperform  = st.sidebar.checkbox("Hanya Market RS = Outperform", value=True)
show_breakout_only = st.sidebar.checkbox("Hanya 20D Breakout", value=False)

# FIX: filter baru yang lebih pintar
st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Filter Proteksi v13")
only_adx_bullish    = st.sidebar.checkbox("Hanya DI+ > DI- (ADX Bullish)", value=True)
exclude_adx_falling = st.sidebar.checkbox("Exclude ADX Trend = Falling", value=True)
exclude_divergence  = st.sidebar.checkbox("Exclude Bearish Divergence", value=True)

today   = date.today()
start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
end_d   = st.sidebar.date_input("Tanggal Akhir", today)

st.sidebar.markdown("---")
btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True, type="primary")

# ─────────────────────────────────────────────
# 8. OUTPUT
# ─────────────────────────────────────────────
STYLE_COLS_BASE = {
    'subset_mfi':       ['MFI (14D)'],
    'subset_rs':        ['Market RS'],
    'subset_pva':       ['PVA'],
    'subset_ma':        ['Above MA20'],
    'subset_rvol':      ['Rel Vol (20D)'],
    'subset_adx':       ['ADX (14)'],
    'subset_div':       ['Divergence Warning'],
    'subset_adxtrend':  ['ADX Trend'],
    'subset_adxdir':    ['ADX Direction'],
}

FORMAT_DICT = {
    'Rel Vol (20D)':      "{:.2f}x",
    'Rel Vol (50D)':      "{:.2f}x",
    'Free Float (%)':     "{:.2f}%",
    'MFI (14D)':          "{:.2f}",
    'MFI Change 5D':      "{:+.2f}",
    'RSI (14)':           "{:.2f}",
    'ADX (14)':           "{:.2f}",
    'Dist to 20D High (%)': "{:.2f}%"
}

def apply_full_style(df_styled):
    return (df_styled
            .map(style_mfi,             subset=['MFI (14D)'])
            .map(style_market_rs,       subset=['Market RS'])
            .map(style_pva,             subset=['PVA'])
            .map(style_ma_filter,       subset=['Above MA20'])
            .map(style_rel_vol,         subset=['Rel Vol (20D)'])
            .map(style_adx,             subset=['ADX (14)'])
            .map(style_divergence,      subset=['Divergence Warning'])
            .map(style_adx_trend,       subset=['ADX Trend'])
            .map(style_adx_dir,         subset=['ADX Direction'])
            .map(style_chart_analysis,  subset=['Chart Analysis'])
            .format(FORMAT_DICT))

if btn_analisa:
    with st.spinner('Menganalisa market…'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk  = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

        if not df_c.empty:
            df_res, shortlist = get_signals_and_data(
                df_c, df_v, df_h, df_l, df_emiten, min_vol_lot)

            # ── Filter umum ──
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

                # ── Filter proteksi v13 ──
                if only_adx_bullish:
                    mask &= df_res['ADX Direction'] == 'Bullish (DI+>DI-)'
                if exclude_adx_falling:
                    mask &= df_res['ADX Trend'] != 'Falling'
                if exclude_divergence:
                    mask &= df_res['Divergence Warning'] == ''

                df_res = df_res[mask]

            # ── Shortlist ──
            st.subheader("🔥 Smart Money Shortlist v14 (Siap Terbang)")
            df_s = df_res[df_res['Kode Saham'].isin(shortlist)] if not df_res.empty else pd.DataFrame()

            if not df_s.empty:
                st.dataframe(
                    apply_full_style(df_s.style),
                    use_container_width=True
                )

                # Ringkasan per saham
                st.markdown("#### 📋 Ringkasan Kandidat Shortlist")
                for _, row in df_s.iterrows():
                    di_icon = "🟢" if row['ADX Direction'] == 'Bullish (DI+>DI-)' else "🔴"
                    st.markdown(
                        f"**{row['Kode Saham']}** | Harga: Rp {row['Last Price']:,} | "
                        f"RSI: {row['RSI (14)']:.1f} | ADX: {row['ADX (14)']:.1f} "
                        f"{di_icon} {row['ADX Direction']} | "
                        f"MFI: {row['MFI (14D)']:.1f} ({row['MFI Change 5D']:+.1f}) | "
                        f"RelVol20: {row['Rel Vol (20D)']:.2f}x | "
                        f"*{row['Shortlist Reasons']}*"
                    )
            else:
                st.info("Belum ada kandidat yang memenuhi kriteria super ketat hari ini.")

            # ── Semua Hasil ──
            st.markdown("---")
            st.subheader("🔍 Seluruh Hasil Analisa")
            if not df_res.empty:
                st.dataframe(
                    apply_full_style(df_res.style),
                    use_container_width=True,
                    height=500
                )
            else:
                st.info("Tidak ada data yang memenuhi filter.")

            # ── AI Chart Analysis On-Demand ──
            st.markdown("---")
            st.subheader("🤖 AI Chart Analysis (On-Demand)")
            st.caption(
                "Klik tombol di bawah untuk analisa chart saham tertentu. "
                "Claude akan melihat chart Yahoo Finance + data OHLCV 30 hari terakhir "
                "dan memberikan label kondisi teknikal."
            )

            if not df_res.empty:
                ticker_options = sorted(df_res['Kode Saham'].tolist())
                col_sel, col_btn = st.columns([3, 1])
                with col_sel:
                    selected_for_ai = st.selectbox(
                        "Pilih saham untuk dianalisa:", ticker_options,
                        key="ai_chart_select"
                    )
                with col_btn:
                    st.write("")  # spacer
                    run_ai = st.button("🔍 Analisa Chart", type="primary", key="run_ai_btn")

                if run_ai and selected_for_ai:
                    with st.spinner(f"Claude sedang analisa chart {selected_for_ai}…"):
                        result = ai_chart_analysis(selected_for_ai)

                    label    = result["label"]
                    reason   = result["reasoning"]
                    has_ss   = result["has_screenshot"]

                    # Color map untuk label
                    label_color = {
                        "Overextended 🚨":       "#ff4b4b",
                        "Breakout Valid 🚀":      "#1a8c1a",
                        "Pullback Healthy 👍":    "#2196F3",
                        "Uptrend Normal":         "#4CAF50",
                        "Downtrend ❌":            "#cc0000",
                        "Sideways / Konsolidasi": "#888888",
                    }
                    color = next(
                        (v for k, v in label_color.items() if k in label),
                        "#888888"
                    )

                    st.markdown(
                        f"### {selected_for_ai} &nbsp; "
                        f'<span style="background:{color};color:white;'
                        f'padding:4px 14px;border-radius:20px;font-size:1em;">'
                        f"{label}</span>",
                        unsafe_allow_html=True
                    )
                    st.markdown(f"**Analisa:** {reason}")

                    src_note = "📸 Screenshot Yahoo Finance + data OHLCV" if has_ss else "📊 Data OHLCV saja (screenshot gagal)"
                    st.caption(f"Sumber: {src_note} · "
                               f"[Lihat chart Yahoo Finance ↗](https://finance.yahoo.com/quote/{selected_for_ai}.JK/)")

                    # Tampilkan screenshot jika berhasil
                    if has_ss:
                        png_bytes = screenshot_yahoo_chart(selected_for_ai + ".JK")
                        if png_bytes:
                            with st.expander("📷 Screenshot Chart Yahoo Finance"):
                                st.image(png_bytes, use_container_width=True)

            # ── Download ──
            excel_data = to_excel_report(df_s if not df_s.empty else pd.DataFrame(), df_res)
            st.sidebar.download_button(
                label="📥 Download Report Excel v15",
                data=excel_data,
                file_name=f"Analisa_BEI_{date.today()}_v15.xlsx",
                mime="application/vnd.ms-excel"
            )

            # ── Legenda ──
            with st.expander("📖 Legenda Indikator v15"):
                st.markdown("""
| Kolom | Penjelasan |
|---|---|
| **MFI (14D)** | Money Flow Index 14 hari. > 80 = overbought (merah), < 40 = oversold (hijau) |
| **MFI Change 5D** | Perubahan MFI dalam 5 hari terakhir. Positif = uang masuk |
| **RSI (14)** | Relative Strength Index. Ideal entry: 40–70 |
| **ADX (14)** | Kekuatan tren. > 25 = tren kuat (biru) |
| **ADX Direction** | **DI+ > DI-** = tren naik. **DI- > DI+** = tren turun. Shortlist hanya terima Bullish |
| **ADX Trend** | Apakah kekuatan ADX sedang Rising/Falling/Flat |
| **ADX Strength** | Weak / Moderate / Strong / Very Strong |
| **Divergence Warning** | Harga buat higher high tapi MFI lower high = potensi reversal |
| **PVA** | Price Volume Analysis: konfirmasi volume terhadap arah harga |
| **Market RS** | Kinerja saham vs IHSG 20 hari terakhir |
| **Rel Vol (20D)** | Volume hari ini vs rata-rata 20 hari |
| **Rel Vol (50D)** | Volume hari ini vs rata-rata 50 hari — baseline lebih stabil |
| **Chart Analysis** 🆕 | `Overextended 🚨` terlalu jauh MA20 · `Breakout Valid 🚀` baru breakout sehat · `Pullback Healthy 👍` retrace ke MA20, entry bagus · `Uptrend Normal` tren naik biasa · `Downtrend ❌` hindari · `Sideways / Konsolidasi` belum jelas |
| **AI Chart Analysis** 🆕 | Analisa oleh Claude berdasarkan screenshot chart Yahoo Finance + data OHLCV. Klik tombol "Analisa Chart" per saham. |
""")


        else:
            st.error("Data gagal diambil untuk range tanggal tersebut. Coba perlebar range tanggal.")

else:
    st.info(
        f"📂 Database: **{loaded_file}**\n\n"
        "**Perubahan utama v15:**\n"
        "- 🆕 ADX sekarang cek DI+ vs DI- — tidak ada lagi sinyal palsu tren turun\n"
        "- 🆕 Bearish Divergence otomatis ditolak dari Shortlist\n"
        "- 🆕 ADX Falling tidak masuk Shortlist\n"
        "- 🆕 Rel Vol 50D sebagai baseline tambahan\n"
        "- 🆕 MFI threshold konsisten (55–85) untuk Shortlist\n"
        "- 🆕 **AI Chart Analysis**: klik tombol per saham → Claude analisa chart Yahoo Finance + OHLCV"
    )
