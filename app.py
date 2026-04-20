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
st.set_page_config(page_title="Monitor Saham BEI v16", layout="wide")
st.title("🚀 Dashboard Akumulasi: Smart Money Monitor v16 – Pre-Breakout Radar")

st.markdown("""
**Update v16:**
- ✅ Semua fitur v15 dipertahankan
- 🆕 **Opsi A: Pre-Breakout Watch List** — tangkap saham dengan MFI Change tinggi SEBELUM breakout/consec up
- 🆕 **Opsi C: Early Momentum Score** — skor komposit MFI Change + ADX Rising + Above MA20 sebagai sinyal awal
- 💡 Terinspirasi dari MDIA (17 Apr): MFI Change tertinggi +72.7, ADX Rising, tapi belum breakout — naik +21% esoknya
""")

# ─────────────────────────────────────────────
# 1. CACHE DATA
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, start_date, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
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
# 6. FUNGSI ANALISA UTAMA v16
# ─────────────────────────────────────────────
def get_signals_and_data(df_c, df_v, df_h, df_l, df_ref, min_vol_lot,
                          min_mfi_change_watch, min_early_score,
                          watch_require_outperform):
    results = []
    shortlist_keys = []
    prebreakout_keys = []
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

        if len(c) < 55:
            continue

        # ── Volume filter ──
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        avg_vol50 = v.rolling(50).mean().iloc[-1]
        if avg_vol20 < min_vol_lembar:
            continue

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
            len(reasons) >= 3
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
            not is_shortlist  # jangan duplikat dengan shortlist
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

        if is_watch:
            prebreakout_keys.append(ticker_name)

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
            'Early Momentum Score':  early_score,        # OPSI C
            'Pre-Breakout Watch':    '🔭 Watch' if is_watch else '',  # OPSI A
            'Shortlist Reasons':     ", ".join(reasons) if reasons else "",
            'Chart Analysis':        chart_analysis,
        })

    df_results = pd.DataFrame(results)
    return df_results, shortlist_keys, prebreakout_keys

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
st.sidebar.subheader("⚡ Opsi C: Early Momentum Score")
st.sidebar.caption("Skor 0–10 gabungan: MFI Change + ADX Rising + MA20 + RSI + Float kecil. "
                   "Saham dengan skor tinggi tapi belum shortlist = kandidat liar.")
min_early_score = st.sidebar.slider(
    "Min Early Momentum Score untuk Watch", min_value=0, max_value=10, value=5,
    help="Skor ≥ 6 = kandidat kuat. Skor ≥ 8 = potensi explosive (tapi berisiko)")
show_score_in_table = st.sidebar.checkbox("Tampilkan kolom Early Momentum Score", value=True)

today   = date.today()
start_d = st.sidebar.date_input("Tanggal Mulai", today - timedelta(days=30))
end_d   = st.sidebar.date_input("Tanggal Akhir", today)

st.sidebar.markdown("---")
btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True, type="primary")

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

def apply_full_style(df_styled, include_score=True, include_watch=False):
    styled = (df_styled
              .map(style_mfi,           subset=['MFI (14D)'])
              .map(style_market_rs,     subset=['Market RS'])
              .map(style_pva,           subset=['PVA'])
              .map(style_ma_filter,     subset=['Above MA20'])
              .map(style_rel_vol,       subset=['Rel Vol (20D)'])
              .map(style_adx,           subset=['ADX (14)'])
              .map(style_divergence,    subset=['Divergence Warning'])
              .map(style_adx_trend,     subset=['ADX Trend'])
              .map(style_adx_dir,       subset=['ADX Direction'])
              .map(style_chart_analysis,subset=['Chart Analysis'])
              .format(FORMAT_DICT, na_rep="-"))
    if include_score and 'Early Momentum Score' in df_styled.data.columns:
        styled = styled.map(style_early_momentum, subset=['Early Momentum Score'])
    if include_watch and 'Pre-Breakout Watch' in df_styled.data.columns:
        styled = styled.map(style_prebreakout, subset=['Pre-Breakout Watch'])
    return styled

# ─────────────────────────────────────────────
# 9. OUTPUT UTAMA
# ─────────────────────────────────────────────
if btn_analisa:
    with st.spinner('Menganalisa market…'):
        active_list = selected_tickers if selected_tickers else target_list
        tickers_jk  = [k + ".JK" for k in active_list]
        df_c, df_v, df_h, df_l = fetch_yf_all_data(tuple(tickers_jk), start_d, end_d)

        if not df_c.empty:
            df_res, shortlist, prebreakout_list = get_signals_and_data(
                df_c, df_v, df_h, df_l, df_emiten, min_vol_lot,
                min_mfi_change_watch=min_mfi_change_watch,
                min_early_score=min_early_score,
                watch_require_outperform=watch_require_outperform,
            )

            # ── Filter umum (berlaku untuk semua tabel) ──
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
            else:
                df_res_filtered = df_res.copy()

            # Kolom yang ditampilkan (kondisional Early Momentum Score)
            base_cols = [
                'Kode Saham', 'Free Float (%)', 'MFI (14D)', 'MFI Change 5D',
                'RSI (14)', 'ADX (14)', 'ADX Direction', 'ADX Trend', 'ADX Strength',
                'Divergence Warning', 'PVA', 'Market RS', 'Above MA20', '20D Breakout',
                'Dist to 20D High (%)', 'Last Price', 'Rel Vol (20D)', 'Rel Vol (50D)',
                'Consec Up Days', 'AvgVol20 (Lot)',
            ]
            score_col  = ['Early Momentum Score'] if show_score_in_table else []
            watch_col  = ['Pre-Breakout Watch']
            reason_col = ['Shortlist Reasons', 'Chart Analysis']

            all_display_cols = base_cols + score_col + watch_col + reason_col

            # ── TAB LAYOUT ──
            tab1, tab2, tab3 = st.tabs([
                "🔥 Shortlist Utama",
                "🔭 Pre-Breakout Watch (Opsi A)",
                "🔍 Semua Hasil Analisa",
            ])

            # ═══════════════════════════════════════
            # TAB 1: SHORTLIST UTAMA
            # ═══════════════════════════════════════
            with tab1:
                st.subheader("🔥 Smart Money Shortlist v16 (Siap Terbang)")
                df_s = (df_res_filtered[df_res_filtered['Kode Saham'].isin(shortlist)]
                        if not df_res_filtered.empty else pd.DataFrame())

                if not df_s.empty:
                    cols_s = [c for c in base_cols + score_col + reason_col if c in df_s.columns]
                    st.dataframe(
                        apply_full_style(df_s[cols_s].style, include_score=show_score_in_table),
                        use_container_width=True
                    )

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
                        # Sort by Early Momentum Score descending
                        df_watch = df_watch.sort_values('Early Momentum Score', ascending=False)
                    else:
                        df_watch = pd.DataFrame()

                    if not df_watch.empty:
                        cols_w = [c for c in base_cols + score_col + reason_col if c in df_watch.columns]
                        st.dataframe(
                            apply_full_style(
                                df_watch[cols_w].style,
                                include_score=show_score_in_table
                            ),
                            use_container_width=True
                        )

                        st.markdown("#### 📋 Ringkasan Pre-Breakout Candidates")
                        for _, row in df_watch.iterrows():
                            sc = int(row['Early Momentum Score'])
                            score_badge = "🟠" if sc >= 6 else "🟡"
                            ff_note = " ⚡Float kecil!" if row['Free Float (%)'] < 15 else ""
                            st.markdown(
                                f"{score_badge} **{row['Kode Saham']}** | "
                                f"Harga: Rp {row['Last Price']:,} | "
                                f"MFI Change: **{row['MFI Change 5D']:+.1f}** | "
                                f"ADX Trend: {row['ADX Trend']} | "
                                f"Consec Up: {row['Consec Up Days']} hari | "
                                f"Rel Vol: {row['Rel Vol (20D)']:.2f}x | "
                                f"Score: **{sc}**/10{ff_note}"
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
            # TAB 3: SEMUA HASIL ANALISA
            # ═══════════════════════════════════════
            with tab3:
                st.subheader("🔍 Seluruh Hasil Analisa")

                # Sort option
                sort_col = st.selectbox(
                    "Urutkan berdasarkan:",
                    options=['Early Momentum Score', 'MFI Change 5D', 'MFI (14D)', 'Rel Vol (20D)', 'ADX (14)'],
                    index=0
                )
                df_sorted = (df_res_filtered.sort_values(sort_col, ascending=False)
                             if not df_res_filtered.empty else df_res_filtered)

                if not df_sorted.empty:
                    cols_all = [c for c in all_display_cols if c in df_sorted.columns]
                    st.dataframe(
                        apply_full_style(
                            df_sorted[cols_all].style,
                            include_score=show_score_in_table,
                            include_watch=True
                        ),
                        use_container_width=True,
                        height=500
                    )
                else:
                    st.info("Tidak ada data yang memenuhi filter.")

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
                # Prioritaskan shortlist + prebreakout di dropdown
                priority       = shortlist + [k for k in prebreakout_list if k not in shortlist]
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
            excel_data = to_excel_report(df_s_dl, df_w_dl, df_res_filtered)
            st.sidebar.download_button(
                label="📥 Download Report Excel v16",
                data=excel_data,
                file_name=f"Analisa_BEI_{date.today()}_v16.xlsx",
                mime="application/vnd.ms-excel"
            )

            # ── Legenda ──
            with st.expander("📖 Legenda Indikator v16"):
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
| **Early Momentum Score** 🆕 | Skor 0–10 sinyal awal: MFI Change + ADX Rising + MA20 + RSI + Float. ≥6 = menarik, ≥8 = kuat |
| **Pre-Breakout Watch** 🆕 | `🔭 Watch` = saham dengan sinyal akumulasi awal tapi belum breakout. Pantau 1–3 hari ke depan |
""")

        else:
            st.error("Data gagal diambil untuk range tanggal tersebut. Coba perlebar range tanggal.")

else:
    st.info(
        f"📂 Database: **{loaded_file}**\n\n"
        "**Perubahan utama v16:**\n"
        "- 🆕 **Opsi A — Pre-Breakout Watch List**: tangkap saham dengan MFI Change tinggi SEBELUM harga breakout\n"
        "- 🆕 **Opsi C — Early Momentum Score**: skor komposit 0–10, saham dengan skor ≥ 6 tapi belum shortlist = kandidat radar\n"
        "- 🆕 Tab terpisah: Shortlist Utama | Pre-Breakout Watch | Semua Analisa\n"
        "- 🆕 Sort tabel 'Semua Analisa' by Early Momentum Score (default) — kandidat terbaik di atas\n"
        "- 🆕 Download Excel sekarang include sheet 'Pre-Breakout Watch'\n"
        "- ✅ Semua fitur v15 dipertahankan (AI Chart Analysis, ADX DI+/DI-, dll)"
    )
