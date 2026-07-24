import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
from io import BytesIO
import ta
import requests
import base64
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ═══════════════════════════════════════════════════════════════════════════════
# WYCKOFF PHASE DETECTOR  —  v26 (embedded)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_phase_a_selling_climax(
    close_s, volume_s, high_s, low_s,
    lookback=60, vol_threshold=3.0, drop_threshold=0.15, wick_ratio=1.5,
):
    """
    Deteksi Selling Climax (Phase A Wyckoff) dalam window lookback hari terakhir.
    Kriteria: volume >= vol_threshold x avg20, price drop >= drop_threshold dari high,
    dan ada rejection candle (lower wick panjang atau close tidak di titik low).
    Returns dict: had_sc, sc_vol_ratio, sc_price_drop_pct, sc_days_ago, sc_price.
    """
    import pandas as pd
    import numpy as np
    empty = {"had_sc": False, "sc_vol_ratio": 0.0, "sc_price_drop_pct": 0.0,
             "sc_days_ago": -1, "sc_price": 0.0}
    if len(close_s) < lookback + 25:
        return empty
    c = close_s.tail(lookback).reset_index(drop=True)
    v = volume_s.tail(lookback).reset_index(drop=True)
    h = high_s.tail(lookback).reset_index(drop=True)
    l = low_s.tail(lookback).reset_index(drop=True)
    high_60d = float(high_s.tail(lookback).max())
    best_sc, best_vol_ratio = None, 0.0
    for i in range(20, len(c)):
        today_vol  = float(v.iloc[i])
        avg_vol_20 = float(v.iloc[i-20:i].mean())
        if avg_vol_20 <= 0:
            continue
        vol_ratio = today_vol / avg_vol_20
        if vol_ratio < vol_threshold:
            continue
        today_close = float(c.iloc[i])
        price_drop  = (high_60d - today_close) / high_60d if high_60d > 0 else 0.0
        if price_drop < drop_threshold:
            continue
        open_approx = float(c.iloc[i-1])
        today_low   = float(l.iloc[i])
        body        = abs(today_close - open_approx)
        lower_wick  = max(open_approx - today_low if today_close >= open_approx else today_close - today_low, 0)
        has_rejection = (
            (body > 0 and lower_wick >= wick_ratio * body)
            or (today_close > today_low * 1.01)
        )
        if not has_rejection:
            continue
        if vol_ratio > best_vol_ratio:
            best_vol_ratio = vol_ratio
            best_sc = {
                "had_sc": True,
                "sc_vol_ratio": round(vol_ratio, 2),
                "sc_price_drop_pct": round(price_drop * 100, 1),
                "sc_days_ago": lookback - 1 - i,
                "sc_price": round(today_close, 2),
            }
    return best_sc if best_sc else empty


def detect_phase_c_spring(
    close_s, volume_s, low_s, support_level,
    lookback_days=3, vol_ratio_max=0.85, breach_tolerance=0.03,
):
    """
    Deteksi Phase C Spring (Wyckoff) — fake breakdown lalu balik di atas support.
    Kriteria: low tembus support, close kembali di atas support, volume rendah (lack of supply),
    breach tidak terlalu dalam (< breach_tolerance dari support).
    Returns dict: is_spring, strength, spring_low, spring_vol_ratio, days_ago.
    """
    empty = {"is_spring": False, "strength": "", "spring_low": 0.0,
             "spring_vol_ratio": 0.0, "days_ago": -1}
    if support_level is None or support_level <= 0 or len(close_s) < 25:
        return empty
    avg_vol_20 = float(volume_s.iloc[-21:-1].mean()) if len(volume_s) >= 21 else 0.0
    if avg_vol_20 <= 0:
        return empty
    for days_ago in range(lookback_days):
        idx = -(days_ago + 1)
        today_low   = float(low_s.iloc[idx])
        today_close = float(close_s.iloc[idx])
        today_vol   = float(volume_s.iloc[idx])
        if today_low >= support_level:
            continue
        if today_close <= support_level:
            continue
        breach_pct = (support_level - today_low) / support_level
        if breach_pct > breach_tolerance:
            continue
        vol_ratio = today_vol / avg_vol_20
        if vol_ratio >= vol_ratio_max:
            continue
        strength = "Strong" if vol_ratio < 0.70 else "Normal"
        return {"is_spring": True, "strength": strength,
                "spring_low": round(today_low, 2),
                "spring_vol_ratio": round(vol_ratio, 2),
                "days_ago": days_ago}
    return empty


def detect_shakeout_aggressive(
    close_s, open_s, high_s, low_s, volume_s,
    support_level=None,
    lookback_days=10,
    vol_spike_min=1.8,
    wick_ratio_min=1.5,
    recovery_pct_min=0.005,
):
    """
    Deteksi Shakeout Agresif (v33) — menangkap pola yang TIDAK tertangkap Spring klasik.

    Tipe shakeout yang dideteksi:
      1. VOL-SPIKE SHAKEOUT : volume besar (≥1.8× avg20) + wick bawah panjang + close recovery
      2. PIN-BAR SHAKEOUT   : lower wick ≥ 2.5× body + close di upper 30% range candle
      3. SUPPORT-PIERCE     : low tembus support, close balik atas support (mirip spring tapi
                              toleransi lebih lebar & lookback lebih panjang)
      4. MULTI-DAY SHAKEOUT : 2–3 hari turun berturut + hari terakhir reversal kuat (volume
                              meledak + close jauh di atas low hari itu)

    Returns dict:
        detected       : bool
        shakeout_type  : str  ('Vol-Spike' | 'Pin-Bar' | 'Support-Pierce' | 'Multi-Day' | '')
        strength       : str  ('Kuat' | 'Normal' | '')
        days_ago       : int  (0 = hari ini)
        shakeout_low   : float
        vol_ratio      : float  (volume relatif terhadap avg20)
        wick_ratio     : float  (lower wick / body)
        recovery_pct   : float  (% close di atas low candle)
        score          : int    (0–5, makin tinggi makin meyakinkan)
        reasons        : list[str]
    """
    empty = {
        "detected": False, "shakeout_type": "", "strength": "",
        "days_ago": -1, "shakeout_low": 0.0,
        "vol_ratio": 0.0, "wick_ratio": 0.0, "recovery_pct": 0.0,
        "score": 0, "reasons": [],
    }
    if len(close_s) < 25 or len(open_s) == 0:
        return empty

    avg_vol_20 = float(volume_s.iloc[-21:-1].mean()) if len(volume_s) >= 21 else 0.0
    if avg_vol_20 <= 0:
        return empty

    best = None
    best_score = 0

    for days_ago in range(lookback_days):
        idx = -(days_ago + 1)
        try:
            c  = float(close_s.iloc[idx])
            o  = float(open_s.iloc[idx])
            h  = float(high_s.iloc[idx])
            l  = float(low_s.iloc[idx])
            v  = float(volume_s.iloc[idx])
        except Exception:
            continue

        if h <= l or c <= 0:
            continue

        body        = abs(c - o)
        candle_range = h - l
        lower_wick  = min(o, c) - l          # panjang ekor bawah
        upper_wick  = h - max(o, c)
        vol_ratio   = v / avg_vol_20
        wick_ratio_val = (lower_wick / body) if body > 0 else 0.0
        recovery_pct_val = (c - l) / l if l > 0 else 0.0
        close_position = (c - l) / candle_range if candle_range > 0 else 0.0  # 0=di bawah, 1=di atas

        score = 0
        reasons = []
        detected_types = []

        # ── Tipe 1: VOL-SPIKE SHAKEOUT ──────────────────────────────────────
        # Volume meledak (≥1.8×) + wick bawah panjang + close recovery
        if (vol_ratio >= vol_spike_min
                and lower_wick >= wick_ratio_min * max(body, candle_range * 0.05)
                and close_position >= 0.45):
            detected_types.append("Vol-Spike")
            score += 2
            reasons.append(f"💥 Volume spike {vol_ratio:.1f}× avg20")
            if vol_ratio >= 3.0:
                score += 1; reasons.append("💥 Volume sangat ekstrem (≥3×) +1")
            if close_position >= 0.70:
                score += 1; reasons.append("✅ Close di upper 30% candle (rejection kuat) +1")

        # ── Tipe 2: PIN-BAR SHAKEOUT ────────────────────────────────────────
        # Lower wick ≥ 2.5× body + close di upper 70% candle
        if (body > 0
                and lower_wick >= 2.5 * body
                and close_position >= 0.60
                and lower_wick >= candle_range * 0.35):
            detected_types.append("Pin-Bar")
            score += 2
            reasons.append(f"📌 Pin-Bar: lower wick {lower_wick/body:.1f}× body")
            if lower_wick >= 3.5 * body:
                score += 1; reasons.append("📌 Lower wick sangat panjang (≥3.5× body) +1")

        # ── Tipe 3: SUPPORT-PIERCE (lebih lebar dari Spring klasik) ──────────
        # Low tembus support, close balik atas support, toleransi breach 6%
        if support_level is not None and support_level > 0:
            if (l < support_level
                    and c > support_level
                    and (support_level - l) / support_level <= 0.06):
                detected_types.append("Support-Pierce")
                score += 2
                breach_pct = (support_level - l) / support_level * 100
                reasons.append(f"🛡️ Support-Pierce: tembus {breach_pct:.1f}% lalu close di atas support")
                if vol_ratio < 1.0:
                    score += 1; reasons.append("✅ Volume rendah saat pierce (lack of supply) +1")

        # ── Tipe 4: MULTI-DAY SHAKEOUT ───────────────────────────────────────
        # 2+ hari turun berturut, lalu candle pembalikan dengan vol tinggi + wick panjang
        if days_ago == 0 and len(close_s) >= 4:
            prev1 = float(close_s.iloc[-2])
            prev2 = float(close_s.iloc[-3])
            is_consecutive_down = (prev1 < prev2)
            if is_consecutive_down and c > prev1 and vol_ratio >= 1.5 and close_position >= 0.55:
                detected_types.append("Multi-Day")
                score += 2
                drop_2d = (prev2 - prev1) / prev2 * 100
                reasons.append(f"🔄 Multi-Day: 2 hari turun ({drop_2d:.1f}%) lalu reversal hari ini")
                if vol_ratio >= 2.0:
                    score += 1; reasons.append("✅ Volume reversal kuat +1")

        # Tidak ada tipe yang match
        if not detected_types:
            continue

        # Bonus lintas-tipe
        if len(set(detected_types)) >= 2:
            score += 1; reasons.append(f"⭐ Multi-konfirmasi ({'+'.join(set(detected_types))}) +1")

        if score > best_score:
            best_score = score
            shakeout_type = "+".join(dict.fromkeys(detected_types))  # preserve order, deduplicate
            strength = "Kuat" if score >= 4 else "Normal"
            best = {
                "detected": True,
                "shakeout_type": shakeout_type,
                "strength": strength,
                "days_ago": days_ago,
                "shakeout_low": round(l, 2),
                "vol_ratio": round(vol_ratio, 2),
                "wick_ratio": round(wick_ratio_val, 2),
                "recovery_pct": round(recovery_pct_val * 100, 2),
                "score": min(score, 5),
                "reasons": reasons,
            }

    return best if best else empty


def compute_shakeout_context_warning(
    shakeout_score: int,
    wyckoff_score: int,
    silent_score: int,
    obv_trend: str,
    was_score: int,
    adx_direction: str,
    wyckoff_phase: str,
    vol_trend_ratio: float,
    price_tightness: float,
    free_float: float,
) -> dict:
    """
    Evaluasi konteks di balik Shakeout Score (v33).

    Shakeout Score tinggi TIDAK otomatis = saham akan naik.
    Fungsi ini menilai apakah konteks Wyckoff mendukung atau justru
    memperingatkan potensi jebakan (distribusi terselubung, downtrend, dll).

    Returns dict:
        verdict      : str  ('VALID' | 'WASPADA' | 'JEBAKAN')
        verdict_icon : str  emoji
        confidence   : int  (0–100, seberapa meyakinkan konteks bullish-nya)
        warnings     : list[str]  peringatan spesifik
        supports     : list[str]  faktor pendukung
        action       : str  saran tindakan
    """
    warnings = []
    supports = []
    confidence = 50  # baseline netral

    # ── Faktor PENDUKUNG (konteks bullish) ──────────────────────────────────
    if wyckoff_score >= 7:
        confidence += 20
        supports.append(f"✅ Wyckoff Score tinggi ({wyckoff_score}/10) — akumulasi matang")
    elif wyckoff_score >= 5:
        confidence += 10
        supports.append(f"✅ Wyckoff Score moderat ({wyckoff_score}/10)")

    if silent_score >= 7:
        confidence += 15
        supports.append(f"✅ Silent Score {silent_score}/10 — akumulasi diam-diam aktif")
    elif silent_score >= 5:
        confidence += 8
        supports.append(f"✅ Silent Score {silent_score}/10")

    if obv_trend == "Rising ↑":
        confidence += 15
        supports.append("✅ OBV Rising — smart money masuk secara konsisten")

    if was_score >= 7:
        confidence += 10
        supports.append(f"✅ WAS {was_score}/10 — bandar aktif akumulasi")
    elif was_score >= 5:
        confidence += 5
        supports.append(f"✅ WAS {was_score}/10")

    if "Bullish" in adx_direction:
        confidence += 8
        supports.append("✅ ADX Bullish (DI+ > DI-) — tekanan beli dominan")

    if vol_trend_ratio >= 1.5:
        confidence += 7
        supports.append(f"✅ Vol Trend Ratio {vol_trend_ratio:.1f}× — volume mulai naik diam-diam")

    if price_tightness < 3.0:
        confidence += 5
        supports.append(f"✅ Price Tightness {price_tightness:.1f}% — harga dikontrol ketat")

    if 0 < free_float < 20:
        confidence += 5
        supports.append(f"✅ Free Float {free_float:.0f}% — mudah digerakkan")

    # ── Faktor PERINGATAN (konteks bearish / distribusi) ─────────────────────
    if obv_trend == "Falling ↓":
        confidence -= 25
        warnings.append("🚨 OBV Falling — uang keluar diam-diam, potensi DISTRIBUSI")

    if wyckoff_score <= 3:
        confidence -= 20
        warnings.append(f"⚠️ Wyckoff Score rendah ({wyckoff_score}/10) — belum ada pola akumulasi jelas")

    if silent_score <= 2:
        confidence -= 10
        warnings.append(f"⚠️ Silent Score rendah ({silent_score}/10) — tidak ada akumulasi tersembunyi")

    if "Bearish" in adx_direction or "DI-" in adx_direction:
        confidence -= 20
        warnings.append("🚨 ADX Bearish (DI- > DI+) — tekanan jual masih dominan")

    if "Markup" not in wyckoff_phase and "Spring" not in wyckoff_phase and "Shakeout" not in wyckoff_phase and "Akumulasi" not in wyckoff_phase:
        if wyckoff_score < 4:
            confidence -= 15
            warnings.append("⚠️ Fase Wyckoff belum di akumulasi/spring — shakeout bisa jadi genuine breakdown")

    if vol_trend_ratio < 0.8:
        confidence -= 10
        warnings.append(f"⚠️ Vol Trend Ratio rendah ({vol_trend_ratio:.1f}×) — tidak ada tanda akumulasi volume")

    if was_score <= 2:
        confidence -= 10
        warnings.append(f"⚠️ WAS rendah ({was_score}/10) — sinyal bandar akumulasi lemah")

    if shakeout_score >= 4 and wyckoff_score <= 3 and obv_trend == "Falling ↓":
        confidence -= 15
        warnings.append("🚨 POLA BERBAHAYA: Shakeout kuat tapi akumulasi lemah + OBV turun = kemungkinan jebakan distribusi")

    # ── Verdict ─────────────────────────────────────────────────────────────
    confidence = max(0, min(100, confidence))

    if confidence >= 70:
        verdict      = "VALID"
        verdict_icon = "🟢"
        action       = "Konteks mendukung. Pantau breakout dengan volume konfirmasi sebelum entry."
    elif confidence >= 45:
        verdict      = "WASPADA"
        verdict_icon = "🟡"
        action       = "Konteks campuran. Tunggu konfirmasi tambahan: OBV naik, volume breakout, atau Wyckoff Score meningkat."
    else:
        verdict      = "JEBAKAN"
        verdict_icon = "🔴"
        action       = "Konteks TIDAK mendukung. Shakeout Score tinggi tapi sinyal akumulasi lemah/tidak ada. Hindari entry — risiko distribusi atau breakdown lanjutan."

    return {
        "verdict":      verdict,
        "verdict_icon": verdict_icon,
        "confidence":   confidence,
        "warnings":     warnings,
        "supports":     supports,
        "action":       action,
    }


def compute_wyckoff_sequence_score(
    had_sc, sc_days_ago, silent_score, price_tightness, obv_trend,
    is_spring, spring_strength, is_breakout, rel_vol_20,
    adx_trend, is_adx_bullish, free_float, vol_trend_ratio=1.0,
    shakeout_detected=False, shakeout_strength="", shakeout_score=0,
):
    """
    Composite Wyckoff Sequence Score (0–10).
    Mengukur kelengkapan urutan fase A (SC) → B (akumulasi) → C (spring/shakeout) → D (breakout).
    v33: Phase C diperluas dengan deteksi Shakeout Agresif.
    """
    score = 0
    reasons = []
    # Phase A
    if had_sc:
        if 0 <= sc_days_ago <= 30:
            score += 2; reasons.append(f"✅ SC baru ({sc_days_ago}d lalu) +2")
        else:
            score += 1; reasons.append(f"✅ SC tercatat ({sc_days_ago}d lalu) +1")
    # Phase B
    if silent_score >= 8:
        score += 2; reasons.append("✅ Silent Score ≥8 (akumulasi kuat) +2")
    elif silent_score >= 5:
        score += 1; reasons.append("✅ Silent Score ≥5 +1")
    if price_tightness < 3.0 and obv_trend == "Rising ↑":
        score += 1; reasons.append("✅ Harga ketat + OBV Rising (Phase B konfirmasi) +1")
    # Phase C — Spring (low-volume)
    if is_spring:
        if spring_strength == "Strong":
            score += 3; reasons.append("🌱 Spring KUAT (vol sangat rendah) +3")
        else:
            score += 2; reasons.append("🌱 Spring Normal +2")
        if rel_vol_20 > 2.0:
            score -= 1; reasons.append("⚠️ Spring tapi Rel Vol >2x — konfirmasi lemah -1")
    # Phase C — Shakeout Agresif (v33)
    if shakeout_detected and not is_spring:
        if shakeout_strength == "Kuat":
            score += 3; reasons.append(f"🔥 Shakeout KUAT terdeteksi (score {shakeout_score}/5) +3")
        else:
            score += 2; reasons.append(f"⚡ Shakeout Normal (score {shakeout_score}/5) +2")
    elif shakeout_detected and is_spring:
        score += 1; reasons.append("✅ Spring + Shakeout konfirmasi Phase C +1")
    # Phase D
    if is_breakout == "YA":
        if rel_vol_20 >= 2.0:
            score += 2; reasons.append("🚀 Breakout valid + volume kuat +2")
        else:
            score += 1; reasons.append("🚀 Breakout valid +1")
    if adx_trend == "Rising" and is_adx_bullish:
        score += 1; reasons.append("✅ ADX Rising + Bullish +1")
    # Penalty
    if had_sc and obv_trend == "Falling ↓":
        score -= 1; reasons.append("⚠️ SC ada tapi OBV Falling — waspadai distribusi -1")
    # Bonus
    if 0 < free_float < 15:
        score += 1; reasons.append("✅ Free float <15% (explosive potential) +1")
    return max(0, min(score, 10)), reasons


def compute_wyckoff_accumulation_score(
    silent_score: int,
    price_tightness: float,
    obv_trend: str,
    free_float: float,
    last_adx: float,
    is_adx_bullish: bool,
    last_mfi: float,
    mfi_change_5d: float,
    is_above_ma20: str,
    has_bearish_div: bool,
) -> tuple[int, list[str]]:
    """
    Wyckoff Accumulation Score (WAS) — v27.
    Mengkuantifikasi 6 faktor kunci deteksi akumulasi bandar (pola BSBK-style):

      [1] Phase B Wyckoff — Silent Score ≥ 5 = akumulasi aktif
      [2] Price Tightness < 3% — bandar mengunci harga (supply dikontrol)
      [3] OBV Rising + harga di atas MA20 — smart money masuk diam-diam
      [4] Free Float kecil — explosive potential saat mark-up
      [5] ADX ≥ 35 + DI+ > DI- — tren beli dominan di balik konsolidasi
      [6] MFI ≥ 70 + MFI Change positif — aliran uang masuk konsisten

    Returns: (score 0–10, list of reason strings)
    """
    score = 0
    reasons = []

    # [1] Phase B — Silent Score (akumulasi aktif)
    if silent_score >= 8:
        score += 2
        reasons.append(f"✅ Phase B kuat (Silent {silent_score}≥8) +2")
    elif silent_score >= 5:
        score += 1
        reasons.append(f"✅ Phase B aktif (Silent {silent_score}≥5) +1")

    # [2] Price Tightness — bandar mengunci harga
    if price_tightness < 2.0:
        score += 2
        reasons.append(f"✅ Harga sangat ketat ({price_tightness:.1f}%<2%) +2")
    elif price_tightness < 3.0:
        score += 1
        reasons.append(f"✅ Harga ketat ({price_tightness:.1f}%<3%) +1")

    # [3] OBV Rising + di atas MA20 — smart money masuk diam-diam
    if obv_trend == "Rising ↑" and is_above_ma20 == "YA":
        score += 2
        reasons.append("✅ OBV Rising + Above MA20 (akumulasi tersembunyi) +2")
    elif obv_trend == "Rising ↑":
        score += 1
        reasons.append("✅ OBV Rising +1")

    # [4] Free Float kecil — explosive potential
    if 0 < free_float < 15:
        score += 2
        reasons.append(f"✅ Float {free_float:.1f}%<15% (explosive) +2")
    elif 0 < free_float < 25:
        score += 1
        reasons.append(f"✅ Float {free_float:.1f}%<25% +1")

    # [5] ADX ≥ 35 + DI+ > DI- — tren beli kuat tersembunyi
    if last_adx >= 35 and is_adx_bullish:
        score += 2
        reasons.append(f"✅ ADX {last_adx:.0f}≥35 + DI+>DI- +2")
    elif last_adx >= 25 and is_adx_bullish:
        score += 1
        reasons.append(f"✅ ADX {last_adx:.0f}≥25 + DI+>DI- +1")

    # [6] MFI ≥ 70 + MFI Change positif — aliran uang masuk konsisten
    if last_mfi >= 70 and mfi_change_5d > 0:
        score += 2
        reasons.append(f"✅ MFI {last_mfi:.0f}≥70 + naik ({mfi_change_5d:+.1f}) +2")
    elif last_mfi >= 55 and mfi_change_5d > 0:
        score += 1
        reasons.append(f"✅ MFI {last_mfi:.0f}≥55 + naik +1")

    # Penalty
    if has_bearish_div:
        score -= 2
        reasons.append("⚠️ Bearish Divergence -2")

    final = max(0, min(score, 10))
    return final, reasons


def compute_float_analysis(
    free_float_pct: float,
    avg_vol20_lot: float,
    avg_vol5_lot: float,
    total_shares: int = 0,
    vol5_sum_lot: float = 0.0,
) -> dict:
    """
    Hitung 'Barang' — estimasi supply float yang beredar dan seberapa cepat
    bisa diserap bandar.

    Parameter
    ---------
    free_float_pct  : Free float dalam persen (misal 15.0 = 15%)
    avg_vol20_lot   : Rata-rata volume 20 hari dalam LOT
    avg_vol5_lot    : Rata-rata volume 5 hari dalam LOT  (1 minggu trading)
    total_shares    : Total saham beredar dalam LEMBAR (opsional). Jika 0 →
                      float_lot_est tidak tersedia.
    vol5_sum_lot    : Total volume 5 hari terakhir dalam LOT (untuk hitung
                      Estimasi Lot Terkumpul). Dihitung dari data yang sudah ada.

    Return
    ------
    dict dengan kunci:
      float_lot_est        : Estimasi float dalam lot (0 jika total_shares tidak ada)
      accumulated_lot_est  : Estimasi lot terkumpul 5 hari = Σvol5hr − ADV20×5
                             (selalu bisa dihitung tanpa Total Saham)
      vol_accel_ratio      : ADV5 / ADV20 — seberapa cepat akumulasi minggu ini vs normal
      urgency              : Label urgensi: KRITIS / TINGGI / SEDANG / RENDAH
      pct_swept_5d         : Estimasi % float yang sudah tersapu dalam 5 hari terakhir
                             (hanya valid jika total_shares > 0)
      note                 : Catatan interpretasi singkat
    """
    empty = {
        "float_lot_est":       0,
        "accumulated_lot_est": 0,
        "vol_accel_ratio":     0.0,
        "urgency":             "N/A",
        "pct_swept_5d":        0.0,
        "note":                "Data tidak cukup",
    }

    if avg_vol20_lot <= 0:
        return empty

    # ── Hitung float dalam lot jika total_shares tersedia ──
    float_lot_est = 0
    if total_shares > 0 and free_float_pct > 0:
        float_lot_est = int((free_float_pct / 100.0) * total_shares / 100)

    # ── Estimasi Lot Terkumpul: Σ volume 5 hari − ADV20×5 ──
    # Mengukur "kelebihan" volume vs baseline — proxy berapa lot yang sudah
    # diserap bandar dalam 5 hari terakhir. Selalu bisa dihitung tanpa Total Saham.
    baseline_5d = avg_vol20_lot * 5
    if vol5_sum_lot > 0:
        accumulated_lot_est = max(0, round(vol5_sum_lot - baseline_5d))
    else:
        # Fallback jika vol5_sum_lot tidak dikirim (backward compat)
        accumulated_lot_est = max(0, round(avg_vol5_lot * 5 - baseline_5d))

    # ── Volume Acceleration Ratio (ADV5 / ADV20) ──
    vol_accel_ratio = round(avg_vol5_lot / avg_vol20_lot, 2) if avg_vol20_lot > 0 else 0.0

    # ── % Float tersapu dalam 5 hari terakhir ──
    pct_swept_5d = 0.0
    if float_lot_est > 0 and avg_vol5_lot > 0:
        swept_5d = avg_vol5_lot * 5
        pct_swept_5d = round((swept_5d / float_lot_est) * 100, 1)

    # ── Urgency label — berbasis vol_accel (selalu tersedia) ──
    if vol_accel_ratio >= 5.0:
        urgency = "🔴 KRITIS"
    elif vol_accel_ratio >= 3.0:
        urgency = "🟠 TINGGI"
    elif vol_accel_ratio >= 2.0:
        urgency = "🟡 SEDANG"
    else:
        urgency = "🟢 RENDAH"

    # ── Interpretasi ──
    accum_str = f"{accumulated_lot_est:,}" if accumulated_lot_est > 0 else "0"
    if float_lot_est > 0:
        note = (
            f"Float ~{float_lot_est:,} lot | "
            f"Lot terkumpul 5hr ~{accum_str} lot (vs baseline ADV20×5) | "
            f"Akselerasi {vol_accel_ratio:.1f}x | "
            f"~{pct_swept_5d}% float tersapu 5hr terakhir"
        )
    else:
        note = (
            f"Lot terkumpul 5hr ~{accum_str} lot (vs baseline ADV20×5) | "
            f"Akselerasi volume minggu ini {vol_accel_ratio:.1f}x vs normal 20hr"
        )

    return {
        "float_lot_est":       float_lot_est,
        "accumulated_lot_est": accumulated_lot_est,
        "vol_accel_ratio":     vol_accel_ratio,
        "urgency":             urgency,
        "pct_swept_5d":        pct_swept_5d,
        "note":                note,
    }


def style_float_urgency(val):
    """CSS styling untuk kolom Float Urgency."""
    v = str(val)
    if "KRITIS" in v: return "background-color: #c0392b; color: white; font-weight:bold"
    if "TINGGI" in v: return "background-color: #e67e22; color: white; font-weight:bold"
    if "SEDANG" in v: return "background-color: #f1c40f; color: black"
    if "RENDAH" in v: return "background-color: #27ae60; color: white"
    return ""


def style_accumulated_lot(val):
    """CSS styling untuk kolom Estimasi Lot Terkumpul."""
    try:
        n = float(str(val).replace(',', '').replace('-', '0') or 0)
        if n <= 0:  return ""
        if n >= 500_000: return "background-color: #c0392b; color: white; font-weight:bold"
        if n >= 100_000: return "background-color: #e67e22; color: white"
        if n >= 20_000:  return "background-color: #f1c40f; color: black"
        return ""
    except Exception:
        return ""


def style_vol_accel(val):
    """CSS styling untuk kolom Vol Accel Ratio."""
    try:
        n = float(val)
        if n >= 5.0: return "background-color: #c0392b; color: white; font-weight:bold"
        if n >= 3.0: return "background-color: #e67e22; color: white"
        if n >= 2.0: return "background-color: #f1c40f; color: black"
        return ""
    except Exception:
        return ""


def style_was(val):
    """CSS styling untuk kolom Wyckoff Accumulation Score (WAS)."""
    try:
        n = float(val)
        if n >= 9: return "background-color: #004d00; color: white; font-weight:bold"
        if n >= 7: return "background-color: #1a7a1a; color: white; font-weight:bold"
        if n >= 5: return "background-color: #52b352; color: white"
        if n >= 3: return "background-color: #a8d8a8; color: #1a3a1a"
    except Exception:
        pass
    return ""


def style_jalur_masuk(val):
    """CSS styling untuk kolom Jalur Masuk."""
    v = str(val)
    if "Wyckoff Accum" in v: return "background-color: #1a3a7a; color: white; font-weight:bold"
    if "Momentum + Wyckoff" in v: return "background-color: #7a1a7a; color: white; font-weight:bold"
    if "Momentum" in v: return "background-color: #555; color: white"
    return ""


def wyckoff_phase_label(wyckoff_score, is_spring, is_breakout, silent_score, had_sc,
                        shakeout_detected=False, shakeout_strength=""):
    """Label fase Wyckoff saat ini berdasarkan sinyal dominan. v33: +Shakeout."""
    if is_breakout == "YA" and wyckoff_score >= 6:
        return "Phase D — Markup 🚀"
    if is_breakout == "YA":
        return "Phase D — Breakout ⚡"
    if is_spring and shakeout_detected:
        return "Phase C — Spring+Shakeout 🔥"
    if is_spring:
        return "Phase C — Spring 🌱"
    if shakeout_detected:
        label = "Kuat 🔥" if shakeout_strength == "Kuat" else "⚡"
        return f"Phase C — Shakeout {label}"
    if silent_score >= 5:
        return "Phase B — Akumulasi 🔍"
    if had_sc:
        return "Phase A — SC Detected 💥"
    return "Pre-Wyckoff ❓"


def style_wyckoff_score(val):
    """CSS styling untuk kolom Wyckoff Score (0–10)."""
    try:
        n = int(val)
        if n >= 8: return "background-color: #00441b; color: white; font-weight:bold"
        if n >= 6: return "background-color: #238b45; color: white"
        if n >= 4: return "background-color: #74c476; color: black"
        if n >= 2: return "background-color: #c7e9c0; color: black"
    except Exception:
        pass
    return ""


def style_wyckoff_phase(val):
    """CSS styling untuk kolom Wyckoff Phase. v33: +Shakeout."""
    v = str(val)
    if "Markup"    in v: return "background-color: #00441b; color: white; font-weight:bold"
    if "Breakout"  in v: return "background-color: #238b45; color: white"
    if "Shakeout"  in v and "Kuat" in v: return "background-color: #b2182b; color: white; font-weight:bold"
    if "Shakeout"  in v: return "background-color: #d6604d; color: white; font-weight:bold"
    if "Spring"    in v: return "background-color: #e6550d; color: white; font-weight:bold"
    if "Akumulasi" in v: return "background-color: #3182bd; color: white"
    if "SC"        in v: return "background-color: #756bb1; color: white"
    return ""


# ─────────────────────────────────────────────
# BROKER SUMMARY MODULE — EMBEDDED (v20)
# Sumber: broker_summary_module.py (Remora Trader Screener)
# ─────────────────────────────────────────────
import time

BROKER_MODULE_AVAILABLE = True  # always available (embedded)

# ── Klasifikasi Broker (Remora Day 3, 4, 5) ──
SMART_MONEY_BROKERS = {
    "OD", "ES", "HD", "AK", "ZP", "BK", "AI", "AZ",
    "MG", "CP", "RF", "YJ", "RX", "FS", "DX",
}
RETAIL_BROKERS = {
    "YP", "XC", "CC", "KK", "SQ", "XL", "GW", "PD", "DH", "FZ",
}

# ── Stockbit API ──────────────────────────────
# Stockbit menggunakan JWT Bearer token dari login.
# Token disimpan di st.session_state agar tidak login ulang setiap fetch.
_SB_LOGIN_URL  = "https://api.stockbit.com/v2.4/auth/login"
_SB_BROKER_URL = "https://api.stockbit.com/v2.4/symbol/{ticker}/brokerstatistic"
_SB_HEADERS_BASE = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":       "application/json, text/plain, */*",
    "Origin":       "https://stockbit.com",
    "Referer":      "https://stockbit.com/",
}

def _sb_get_token(username: str, password: str) -> str | None:
    """Login ke Stockbit dan return Bearer token. None jika gagal."""
    try:
        r = requests.post(
            _SB_LOGIN_URL,
            json={"username": username, "password": password},
            headers=_SB_HEADERS_BASE,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            # Response: {"data": {"token": "...", "user": {...}}, "message": "OK"}
            token = (data.get("data") or {}).get("token")
            if not token:
                # Coba key alternatif
                token = data.get("token") or data.get("access_token")
            return token
        return None
    except Exception:
        return None


def _sb_headers_auth(token: str) -> dict:
    h = dict(_SB_HEADERS_BASE)
    h["Authorization"] = f"Bearer {token}"
    return h


def _period_to_sb(days: int) -> str:
    """Konversi hari ke format period Stockbit: 1w/1m/3m/6m/1y."""
    if days <= 7:   return "1w"
    if days <= 30:  return "1m"
    if days <= 90:  return "3m"
    if days <= 180: return "6m"
    return "1y"


def _categorize_broker(code: str) -> str:
    if code in SMART_MONEY_BROKERS: return "smart_money"
    if code in RETAIL_BROKERS:      return "retail"
    return "unknown"


def _parse_value_rti(v) -> float:
    """Konversi string RTI seperti '17.2B', '76.1K', '2,258' ke float."""
    if pd.isna(v) or str(v).strip() in ("-", "", "nan", "None"):
        return 0.0
    s = str(v).replace(",", "").strip()
    try:
        if s.upper().endswith("B"):
            return float(s[:-1]) * 1_000_000_000
        elif s.upper().endswith("M"):
            return float(s[:-1]) * 1_000_000
        elif s.upper().endswith("K"):
            return float(s[:-1]) * 1_000
        return float(s)
    except Exception:
        return 0.0


def _is_rti_sidebyside_format(df_raw: pd.DataFrame) -> bool:
    """Deteksi apakah CSV adalah format RTI side-by-side (BY/SL berdampingan)."""
    cols = [str(c).strip().upper() for c in df_raw.columns]
    return len(cols) >= 5 and cols[0] == "BY" and cols[4] == "SL"


def _parse_rti_sidebyside_csv(file_bytes: bytes, ticker: str) -> pd.DataFrame:
    """
    Parse format RTI/IDX broker summary yang side-by-side:
      Kolom: kode_buy | value_buy | lot_buy | avgprice_buy | kode_sell | value_sell | lot_sell | avgprice_sell
    Hasilnya di-reshape menjadi 1 baris per broker dengan kolom standar.
    """
    from io import StringIO as _SI
    text = file_bytes.decode("utf-8-sig")
    df_raw = pd.read_csv(_SI(text), sep=";", header=None, skiprows=2, dtype=str)
    df_raw = df_raw.dropna(how="all")

    rows = []
    for _, r in df_raw.iterrows():
        buy_code  = str(r.iloc[0]).strip() if len(r) > 0 else "-"
        sell_code = str(r.iloc[4]).strip() if len(r) > 4 else "-"

        if buy_code not in ("-", "", "nan", "None"):
            rows.append({
                "broker_code": buy_code.upper(),
                "buy_value":   _parse_value_rti(r.iloc[1] if len(r) > 1 else 0),
                "buy_lot":     _parse_value_rti(r.iloc[2] if len(r) > 2 else 0),
                "sell_value":  0.0,
                "sell_lot":    0.0,
            })
        if sell_code not in ("-", "", "nan", "None"):
            rows.append({
                "broker_code": sell_code.upper(),
                "buy_value":   0.0,
                "buy_lot":     0.0,
                "sell_value":  _parse_value_rti(r.iloc[5] if len(r) > 5 else 0),
                "sell_lot":    _parse_value_rti(r.iloc[6] if len(r) > 6 else 0),
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Gabungkan per broker (satu broker bisa muncul di kedua sisi)
    df = df.groupby("broker_code", as_index=False).sum(numeric_only=True)
    df["net_lot"]   = df["buy_lot"]   - df["sell_lot"]
    df["net_value"] = df["buy_value"] - df["sell_value"]
    df["category"]  = df["broker_code"].apply(_categorize_broker)
    df["ticker"]    = ticker
    return df


def _normalize_broker_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalisasi DataFrame broker dari berbagai format (Stockbit / CSV upload)."""
    col_map = {
        # Stockbit API field names
        "broker": "broker_code", "broker_id": "broker_code",
        "buylot": "buy_lot",  "buy_lot": "buy_lot",  "lot beli": "buy_lot",
        "selllot": "sell_lot", "sell_lot": "sell_lot", "lot jual": "sell_lot",
        "netlot": "net_lot",  "net_lot": "net_lot",
        "buyvalue": "buy_value",  "buy_value": "buy_value",
        "sellvalue": "sell_value", "sell_value": "sell_value",
        "netvalue": "net_value",  "net_value": "net_value",
        # CSV upload aliases
        "kode": "broker_code", "code": "broker_code", "member": "broker_code",
        "buy lot": "buy_lot", "beli (lot)": "buy_lot", "buy (lot)": "buy_lot",
        "sell lot": "sell_lot", "jual (lot)": "sell_lot", "sell (lot)": "sell_lot",
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
    df["category"]    = df["broker_code"].apply(_categorize_broker)
    df["ticker"]      = ticker
    return df


def fetch_broker_summary_stockbit(ticker: str, token: str, days: int = 30) -> pd.DataFrame | None:
    """Ambil broker summary dari Stockbit API menggunakan Bearer token."""
    ticker  = ticker.upper().replace(".JK", "")
    period  = _period_to_sb(days)
    url     = _SB_BROKER_URL.format(ticker=ticker)
    headers = _sb_headers_auth(token)

    for attempt in range(3):
        try:
            r = requests.get(
                url,
                params={"limit": 100, "offset": 0, "period": period},
                headers=headers,
                timeout=15,
            )
            if r.status_code == 401:
                return None  # token expired — caller harus re-login
            if r.status_code == 200:
                data = r.json()
                # Stockbit response: {"data": {"brokers": [...]} , "message": "OK"}
                # atau {"data": [...]}
                inner = data.get("data", {})
                rows  = inner.get("brokers") or inner.get("broker") or (inner if isinstance(inner, list) else [])
                if rows:
                    return _normalize_broker_df(pd.DataFrame(rows), ticker)
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
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


def fetch_broker_scores_batch(tickers: list, token: str, days: int = 30,
                               delay: float = 1.0, progress_callback=None) -> dict:
    """
    Fetch broker summary dari Stockbit untuk batch tickers.
    token : Bearer token dari _sb_get_token()
    Jika token expired di tengah jalan, fungsi berhenti dan return hasil parsial.
    """
    results = {}
    total   = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(
                i / total,
                f"📊 Fetching Stockbit broker: {ticker} ({i+1}/{total})"
            )
        df_b = fetch_broker_summary_stockbit(ticker, token=token, days=days)
        if df_b is None:
            # None bisa berarti token expired atau network error
            results[ticker] = {
                "score": 0, "signal": "No Data",
                "detail": ["❌ Gagal ambil data (token expired atau network error)"],
                "top_buyers": [], "top_sellers": [],
                "smart_net_lot": 0, "retail_net_lot": 0,
                "asing_net_lot": 0, "smart_buy_ratio": 0.0,
            }
        elif df_b.empty:
            results[ticker] = {
                "score": 0, "signal": "No Data",
                "detail": ["⚠️ Data broker kosong dari Stockbit"],
                "top_buyers": [], "top_sellers": [],
                "smart_net_lot": 0, "retail_net_lot": 0,
                "asing_net_lot": 0, "smart_buy_ratio": 0.0,
            }
        else:
            results[ticker] = compute_broker_score(df_b)
        time.sleep(delay)
    if progress_callback:
        progress_callback(1.0, "✅ Selesai!")
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
                file_bytes = f.read()
                # Deteksi format RTI/IDX side-by-side (BY;;;;SL;;;)
                preview = pd.read_csv(
                    __import__("io").BytesIO(file_bytes),
                    sep=";", nrows=0, encoding="utf-8-sig"
                )
                if _is_rti_sidebyside_format(preview):
                    df_b = _parse_rti_sidebyside_csv(file_bytes, ticker)
                else:
                    df_b = pd.read_csv(
                        __import__("io").BytesIO(file_bytes),
                        sep=";", thousands=",", encoding="utf-8-sig"
                    )
                    df_b = _normalize_broker_df(df_b, ticker)
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
st.set_page_config(page_title="Monitor Saham BEI v36", layout="wide")
st.title("📊 Dashboard Akumulasi: Smart Money Monitor v36 – Pre-Explosion Watch")

st.markdown("""
**Update v34 — Pre-Explosion Watch (BB Width + Price Tightness + ADX Flat):**
- 🆕 **Tab Pre-Explosion Watch**: menangkap saham yang "mengisi energi" sebelum pergerakan besar — BB lebar historis + harga ketat + ADX Flat + Above MA20
- 🆕 **BB Width Pct Rank**: kolom baru (0–1) posisi lebar BB saat ini relatif 50 hari terakhir. ≥0.75 = BB sangat lebar
- 🆕 **Explosion Score (0–5)**: skor prioritas gabungan BB Width Rank + Price Tightness + OBV + Float + Vol Trend
- ✅ Semua fitur v33 dipertahankan (Shakeout Agresif, Float Analysis, WAS, Wyckoff Phase Detector, dll)
- 🆕 **v35: Mode Backtest + Hit Rate** — jalankan screener di tanggal historis lalu bandingkan otomatis dengan Top Gainer di tanggal pembanding untuk mengukur hit rate
- 🆕 **v36: Analisa per Rentang Tanggal** — pilih 2 tanggal di kalender untuk melihat total Volume/Value/Hari Naik-Turun/Perubahan Harga sepanjang periode tsb (kolom "...Periode" di tabel & Excel)
- 🆕 **v36: Panel Diagnostik** — expander "🩺 Diagnostik" menunjukkan persis kenapa suatu saham tidak muncul di hasil (data kurang / volume di bawah ambang / gagal fetch dari Yahoo Finance)
""")


# ─────────────────────────────────────────────
# 0. PILIH MODE APLIKASI (v35)
# ─────────────────────────────────────────────
if "app_mode" not in st.session_state:
    st.session_state.app_mode = None

if st.session_state.app_mode is None:
    st.markdown("### 👋 Pilih Mode Aplikasi")
    st.caption("Pilih salah satu mode di bawah untuk melanjutkan. Mode bisa diganti kapan saja lewat sidebar.")
    col_mode1, col_mode2 = st.columns(2)
    with col_mode1:
        with st.container(border=True):
            st.markdown("#### 📊 Regular Screener")
            st.write(
                "Jalankan screener seperti biasa untuk mencari kandidat saham "
                "(Shortlist, Pre-Breakout Watch, Silent Accumulation, dll) per tanggal analisa."
            )
            if st.button("▶️ Mulai Regular Screener", use_container_width=True, type="primary", key="btn_mode_regular"):
                st.session_state.app_mode = "regular"
                st.rerun()
    with col_mode2:
        with st.container(border=True):
            st.markdown("#### 🔁 Backtest + Hit Rate")
            st.write(
                "Jalankan screener di **tanggal historis**, lalu pilih **tanggal pembanding** "
                "untuk mengecek apakah saham hasil screener menjadi Top Gainer pada tanggal tersebut. "
                "Aplikasi otomatis menghitung **hit rate**-nya."
            )
            if st.button("▶️ Mulai Backtest + Hit Rate", use_container_width=True, type="primary", key="btn_mode_backtest"):
                st.session_state.app_mode = "backtest"
                st.rerun()
    st.stop()

IS_BACKTEST_MODE = (st.session_state.app_mode == "backtest")
_mode_label = "🔁 Backtest + Hit Rate" if IS_BACKTEST_MODE else "📊 Regular Screener"
st.sidebar.markdown(f"### Mode aktif: {_mode_label}")
if st.sidebar.button("🔄 Ganti Mode Aplikasi", use_container_width=True):
    st.session_state.app_mode = None
    st.session_state.analisa_hasil = None
    st.rerun()
st.sidebar.markdown("---")


# ─────────────────────────────────────────────
# 1. CACHE DATA
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_yf_all_data(tickers, end_date):
    all_tickers = list(tickers) + ["^JKSE"]
    # ── BACKTEST FIX 1: Lookback 200 hari agar MA50 & BB50 akurat sejak hari pertama ──
    extended_start = end_date - timedelta(days=200)
    # ── BACKTEST FIX 2: yfinance `end` bersifat eksklusif, tambah +1 hari agar
    #    data tanggal end_date benar-benar masuk. Jika end_date = hari ini,
    #    +1 hari tidak masalah karena data future tidak tersedia. ──
    end_exclusive = end_date + timedelta(days=1)
    try:
        df = yf.download(all_tickers, start=extended_start, end=end_exclusive,
                         threads=True, progress=False)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        # ── BACKTEST FIX 3: Potong data agar tidak ada candle setelah end_date ──
        # Konversi end_date ke Timestamp untuk perbandingan index
        end_ts = pd.Timestamp(end_date)
        df = df[df.index <= end_ts]
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
# Data Tradeble Shares seluruh emiten BEI (embedded dari Listed_share.xlsx)
# Total: 959 emiten
_LISTED_SHARES_EMBEDDED = {
    "AADI": 7786891760,
    "AALI": 1924688333,
    "ABBA": 3935892857,
    "ABDA": 620806680,
    "ABMM": 2753165000,
    "ACES": 17120389700,
    "ACRO": 749273042,
    "ACST": 17675160000,
    "ADCP": 22222222200,
    "ADES": 589896800,
    "ADHI": 8407608979,
    "ADMF": 1235803109,
    "ADMG": 3889179559,
    "ADMR": 40882331500,
    "ADRO": 29389689400,
    "AEGS": 1006080721,
    "AGAR": 1000000000,
    "AGII": 3066660000,
    "AGRO": 24493093216,
    "AGRS": 47367057874,
    "AHAP": 4900000000,
    "AIMS": 220000000,
    "AISA": 9311800000,
    "AKKU": 6449463636,
    "AKPI": 612248000,
    "AKRA": 20073474600,
    "AKSI": 720000000,
    "ALDO": 2700713744,
    "ALII": 15825800000,
    "ALKA": 507665055,
    "ALMI": 3816000000,
    "ALTO": 2191870558,
    "AMAG": 5001552516,
    "AMAN": 3873500000,
    "AMAR": 18197283760,
    "AMFG": 434000000,
    "AMIN": 1080000000,
    "AMMN": 61314183036,
    "AMMS": 1235296802,
    "AMOR": 2222222400,
    "AMRT": 41524501700,
    "ANDI": 9350000000,
    "ANJT": 3354175000,
    "ANTM": 24030764725,
    "APEX": 3546466661,
    "APIC": 11766313488,
    "APII": 1075760000,
    "APLI": 1362671400,
    "APLN": 22699326779,
    "ARCI": 25235000000,
    "AREA": 2539601000,
    "ARGO": 3174339029,
    "ARII": 3750000000,
    "ARKA": 2000000000,
    "ARKO": 2928495000,
    "ARMY": 9006250000,
    "ARNA": 7341430976,
    "ARTA": 446674175,
    "ARTI": 7840000000,
    "ARTO": 13722768400,
    "ASBI": 348386472,
    "ASDM": 384000000,
    "ASGR": 1348780500,
    "ASHA": 5000000000,
    "ASII": 40483553140,
    "ASJT": 1400000000,
    "ASLC": 12746354780,
    "ASLI": 6250000000,
    "ASMI": 8958380460,
    "ASPI": 681823317,
    "ASPR": 1420000000,
    "ASRI": 19649411888,
    "ASRM": 1277992036,
    "ASSA": 3691137517,
    "ATAP": 1250000000,
    "ATIC": 2315361355,
    "ATLA": 6199577693,
    "AUTO": 4819733000,
    "AVIA": 61953555600,
    "AWAN": 3435000000,
    "AXIO": 5840126500,
    "AYAM": 4000000000,
    "AYLS": 853423236,
    "BABP": 44014333126,
    "BABY": 1509511321,
    "BACA": 19753494636,
    "BAIK": 1127497572,
    "BAJA": 1800000000,
    "BALI": 3934592500,
    "BANK": 14793174908,
    "BAPA": 661784520,
    "BAPI": 1677762103,
    "BATA": 1300000000,
    "BATR": 3025037353,
    "BAUT": 4800182969,
    "BAYU": 353220780,
    "BBCA": 122042299500,
    "BBHI": 21512953877,
    "BBKP": 185819884852,
    "BBLD": 1645796054,
    "BBMD": 4049189100,
    "BBNI": 36924339786,
    "BBRI": 150043411587,
    "BBRM": 8479490328,
    "BBSI": 3637976068,
    "BBSS": 4800016020,
    "BBTN": 13894099969,
    "BBYB": 13216977523,
    "BCAP": 42618850927,
    "BCIC": 17926071041,
    "BCIP": 1429915525,
    "BDKR": 4725101522,
    "BDMN": 9675817341,
    "BEBS": 45000000000,
    "BEEF": 8120236098,
    "BEER": 4000000000,
    "BEKS": 51351733883,
    "BELI": 137218985689,
    "BELL": 7250000000,
    "BESS": 3440455528,
    "BEST": 9647311150,
    "BFIN": 15039383620,
    "BGTG": 23731287132,
    "BHAT": 5000000000,
    "BHIT": 86068156705,
    "BIKA": 592280000,
    "BIKE": 1293916404,
    "BIMA": 608175716,
    "BINA": 6073369498,
    "BINO": 2275316111,
    "BIPI": 63710196917,
    "BIPP": 5028669376,
    "BIRD": 2502100000,
    "BISI": 3000000000,
    "BJBR": 10275158214,
    "BJTM": 14865343101,
    "BKDP": 7513992252,
    "BKSL": 167708902705,
    "BKSW": 34806467881,
    "BLES": 8890206400,
    "BLOG": 3379487200,
    "BLTA": 25940187103,
    "BLTZ": 873937142,
    "BLUE": 418000000,
    "BMAS": 17921635680,
    "BMBL": 1030080995,
    "BMHS": 8601877576,
    "BMRI": 92399999996,
    "BMSR": 1159200024,
    "BMTR": 16583997586,
    "BNBA": 3354120000,
    "BNBR": 173416832509,
    "BNGA": 24890783784,
    "BNII": 75357433911,
    "BNLI": 35819545925,
    "BOAT": 1000480000,
    "BOBA": 1155750000,
    "BOGA": 3803526210,
    "BOLA": 6000000000,
    "BOLT": 2343750000,
    "BOSS": 1400000000,
    "BPFI": 2673995362,
    "BPII": 9884153240,
    "BPTR": 3534000000,
    "BRAM": 450056980,
    "BREN": 133786220000,
    "BRIS": 45667877639,
    "BRMS": 141784040338,
    "BRNA": 979110000,
    "BRPT": 93747218044,
    "BRRC": 994603036,
    "BSBK": 25091882375,
    "BSDE": 21171365812,
    "BSIM": 19517921842,
    "BSML": 1850225000,
    "BSSR": 2616500000,
    "BSWD": 3651978177,
    "BTEK": 46277496376,
    "BTEL": 36822665755,
    "BTON": 720000000,
    "BTPN": 10536203690,
    "BTPS": 7626663000,
    "BUAH": 2000000000,
    "BUDI": 4498997362,
    "BUKA": 103167090767,
    "BUKK": 2640452000,
    "BULL": 15494436593,
    "BUMI": 371335392068,
    "BUVA": 24617054642,
    "BVIC": 18235266754,
    "BWPT": 31525291000,
    "BYAN": 33333335000,
    "CAKK": 1203300219,
    "CAMP": 5885000000,
    "CANI": 833440000,
    "CARE": 33250000000,
    "CARS": 15000000000,
    "CASA": 54476269803,
    "CASH": 1431125517,
    "CASS": 2086950000,
    "CBDK": 5668944500,
    "CBMF": 1875000000,
    "CBPE": 1356130000,
    "CBRE": 4538067441,
    "CBUT": 3125000000,
    "CCSI": 532521331,
    "CDIA": 49931753900,
    "CEKA": 595000000,
    "CENT": 31183464900,
    "CFIN": 3984520457,
    "CGAS": 1771499039,
    "CHEK": 1624963749,
    "CHEM": 1700014594,
    "CHIP": 806000000,
    "CINT": 1000000000,
    "CITA": 3960361250,
    "CITY": 5405188966,
    "CLAY": 520000000,
    "CLEO": 24000000000,
    "CLPI": 306338500,
    "CMNP": 6696354391,
    "CMNT": 17125504000,
    "CMPP": 10685124441,
    "CMRY": 7934683000,
    "CNKO": 8956361206,
    "CNMA": 83345000000,
    "CNTB": 130000000,
    "CNTX": 70000000,
    "COAL": 6250000000,
    "COCO": 3559455924,
    "COIN": 14705882400,
    "COWL": 4871214021,
    "CPIN": 16398000000,
    "CPRI": 2433379958,
    "CPRO": 59572382787,
    "CRAB": 1950000000,
    "CRSN": 2892000000,
    "CSAP": 5683175151,
    "CSIS": 1829800000,
    "CSMI": 816061500,
    "CSRA": 2050000000,
    "CTBN": 800371500,
    "CTRA": 18535695255,
    "CTTH": 1230839821,
    "CUAN": 112418900000,
    "CYBR": 6732608398,
    "DAAZ": 1997000000,
    "DADA": 7431530800,
    "DART": 3141390962,
    "DATA": 1375000000,
    "DAYA": 2420547025,
    "DCII": 2383745900,
    "DEAL": 1146170959,
    "DEFI": 687266666,
    "DEPO": 6790000000,
    "DEWA": 40687434244,
    "DEWI": 2000000000,
    "DFAM": 1899852850,
    "DGIK": 5541165000,
    "DGNS": 1279651500,
    "DGWG": 5882353000,
    "DIGI": 1625000000,
    "DILD": 10365854185,
    "DIVA": 1428571400,
    "DKFT": 5638246600,
    "DKHH": 2550312624,
    "DLTA": 800659050,
    "DMAS": 48198111100,
    "DMMX": 7692307700,
    "DMND": 9468359000,
    "DNAR": 16721891185,
    "DNET": 14184000000,
    "DOID": 7651007132,
    "DOOH": 7738891036,
    "DOSS": 1725000000,
    "DPNS": 331129952,
    "DPUM": 4175000000,
    "DRMA": 4705882300,
    "DSFI": 1857135500,
    "DSNG": 10599842400,
    "DSSA": 192638080000,
    "DUCK": 1283330000,
    "DUTI": 1850000000,
    "DVLA": 1120000000,
    "DWGL": 9252820991,
    "DYAN": 4272964279,
    "EAST": 4126405336,
    "ECII": 1334333000,
    "EDGE": 2020250000,
    "EKAD": 3493875000,
    "ELIT": 561432633,
    "ELPI": 7412000000,
    "ELSA": 7298500000,
    "ELTY": 43521913019,
    "EMAS": 7350951663,
    "EMDE": 3350000000,
    "EMTK": 61426451483,
    "ENAK": 2166666800,
    "ENRG": 26346230250,
    "ENVY": 1800000000,
    "ENZO": 2162547122,
    "EPAC": 3303400000,
    "EPMT": 2708640000,
    "ERAA": 15950000000,
    "ERAL": 5187500000,
    "ERTX": 1286539792,
    "ESIP": 1109953847,
    "ESSA": 17226975700,
    "ESTA": 2425354179,
    "ESTI": 2015208720,
    "ETWA": 4668671400,
    "EURO": 2548826428,
    "EXCL": 18199862451,
    "FAPA": 3629411800,
    "FAST": 4523610492,
    "FASW": 3221255423,
    "FILM": 10887566758,
    "FIMP": 400000975,
    "FIRE": 1475363179,
    "FISH": 4800000000,
    "FITT": 1080272051,
    "FLMC": 781250000,
    "FMII": 6400000000,
    "FOLK": 4091357544,
    "FOOD": 650000000,
    "FORE": 8918359270,
    "FORU": 465224000,
    "FPNI": 5566414000,
    "FUJI": 1300000000,
    "FUTR": 6635551959,
    "FWCT": 1963000000,
    "GAMA": 10011027656,
    "GDST": 9242500000,
    "GDYR": 410000000,
    "GEMA": 1600000000,
    "GEMS": 5882353000,
    "GGRM": 1924088000,
    "GGRP": 12111376157,
    "GHON": 550000000,
    "GIAA": 407091703837,
    "GJTL": 3484800000,
    "GLOB": 1111112000,
    "GLVA": 1500000000,
    "GMFI": 124835258434,
    "GMTD": 1015380000,
    "GOLD": 1277276000,
    "GOLF": 1950000000,
    "GOLL": 3665000759,
    "GOOD": 36897901455,
    "GOTO": 1140573267220,
    "GOTOM": 50571730000,
    "GPRA": 4276655336,
    "GPSO": 666741103,
    "GRIA": 4201200000,
    "GRPH": 996000000,
    "GRPM": 1548669396,
    "GSMF": 14230399705,
    "GTBO": 2500000000,
    "GTRA": 1894375000,
    "GTSI": 15819142767,
    "GULA": 1070362500,
    "GUNA": 500000000,
    "GWSA": 7800760000,
    "GZCO": 6000000000,
    "HADE": 2120000000,
    "HAIS": 2620231500,
    "HAJJ": 2468527572,
    "HALO": 6078729117,
    "HATM": 8677101900,
    "HBAT": 1040740800,
    "HDFA": 6542445783,
    "HDIT": 1524680000,
    "HEAL": 15365950000,
    "HELI": 832862387,
    "HERO": 4183634000,
    "HEXA": 840000000,
    "HGII": 6500000000,
    "HILL": 14741500000,
    "HITS": 7101084801,
    "HKMU": 3221750000,
    "HMSP": 116318076900,
    "HOKI": 9677752680,
    "HOME": 22212194782,
    "HOMI": 1575000000,
    "HOPE": 2130360203,
    "HOTL": 3550001452,
    "HRME": 5958750000,
    "HRTA": 4605262400,
    "HRUM": 13518100000,
    "HUMI": 18062651987,
    "HYGN": 2525000000,
    "IATA": 31275829981,
    "IBFN": 1517332349,
    "IBOS": 8065789529,
    "IBST": 1350904927,
    "ICBP": 11661908000,
    "ICON": 1089750000,
    "IDEA": 1062437500,
    "IDPR": 2003000000,
    "IFII": 9412000000,
    "IFSH": 2125000000,
    "IGAR": 927780600,
    "IIKP": 33600000000,
    "IKAI": 13305799387,
    "IKAN": 833333000,
    "IKBI": 1224000000,
    "IKPM": 1684662500,
    "IMAS": 3994291039,
    "IMJS": 10849262500,
    "IMPC": 54907000000,
    "INAF": 3099267500,
    "INAI": 633600000,
    "INCF": 1438370465,
    "INCI": 207656617,
    "INCO": 10539784534,
    "INDF": 8780426500,
    "INDO": 4480741638,
    "INDR": 654351707,
    "INDS": 6562497100,
    "INDX": 437913588,
    "INDY": 5210192000,
    "INET": 22374111088,
    "INKP": 5470982941,
    "INOV": 1808221900,
    "INPC": 20021178779,
    "INPP": 11181971732,
    "INPS": 650000000,
    "INRU": 1388883283,
    "INTA": 3343935022,
    "INTD": 591828000,
    "INTP": 3515602799,
    "IOTF": 5290298067,
    "IPAC": 949868500,
    "IPCC": 1818384820,
    "IPCM": 5284811100,
    "IPOL": 6443379509,
    "IPPE": 4600000000,
    "IPTV": 42197950841,
    "IRRA": 397400000,
    "IRSX": 6195047377,
    "ISAP": 4020350519,
    "ISAT": 32250810957,
    "ISEA": 1390013370,
    "ISSP": 7185992035,
    "ITIC": 940720000,
    "ITMA": 999053167,
    "ITMG": 1129925000,
    "JARR": 9230665050,
    "JAST": 1082575738,
    "JATI": 3262520106,
    "JAWA": 16232951842,
    "JAYA": 798499394,
    "JECC": 756000000,
    "JGLE": 22581909405,
    "JIHD": 2329040482,
    "JKON": 16308519860,
    "JMAS": 1000000000,
    "JPFA": 11726575201,
    "JRPT": 12910719100,
    "JSKY": 2032535000,
    "JSMR": 7257871200,
    "JSPT": 2318736000,
    "JTPE": 6852050000,
    "KAEF": 5566589677,
    "KAQI": 2075800000,
    "KARW": 587152700,
    "KAYU": 150000000,
    "KBAG": 7150002603,
    "KBLI": 4007235107,
    "KBLM": 1120000000,
    "KBLV": 1742167907,
    "KBRI": 8687995734,
    "KDSI": 1620000000,
    "KDTN": 1250023298,
    "KEEN": 3651279900,
    "KEJU": 5624999999,
    "KETR": 426200000,
    "KIAS": 14929100000,
    "KICI": 276000000,
    "KIJA": 20824888369,
    "KING": 2602852170,
    "KINO": 1428571500,
    "KIOS": 1075862960,
    "KJEN": 499650000,
    "KKES": 1500000000,
    "KKGI": 5000000000,
    "KLAS": 3644415975,
    "KLBF": 46813391540,
    "KLIN": 1307530330,
    "KMDS": 800000000,
    "KMTR": 8210991379,
    "KOBX": 2272500000,
    "KOCI": 4467412699,
    "KOIN": 980843732,
    "KOKA": 1638113000,
    "KONI": 312000000,
    "KOPI": 697266668,
    "KOTA": 10546185701,
    "KPIG": 99857559263,
    "KRAS": 19346396900,
    "KREN": 18208470100,
    "KRYA": 1663943474,
    "KSIX": 2137831800,
    "KUAS": 1292808150,
    "LABA": 1103402553,
    "LABS": 3950000000,
    "LAJU": 2149942974,
    "LAND": 2792620000,
    "LAPD": 3966350139,
    "LCGP": 5630000914,
    "LCKM": 1000000000,
    "LEAD": 5799616328,
    "LFLO": 1307734937,
    "LIFE": 2100000000,
    "LINK": 2863195484,
    "LION": 520160000,
    "LIVE": 4593005014,
    "LMAS": 787851525,
    "LMAX": 650008775,
    "LMPI": 1008517669,
    "LMSH": 96000000,
    "LOPI": 1100011289,
    "LPCK": 5134685692,
    "LPGI": 3000000000,
    "LPIN": 425000000,
    "LPKR": 70898018369,
    "LPLI": 1170432803,
    "LPPF": 2258279280,
    "LPPS": 2588250000,
    "LRNA": 350000022,
    "LSIP": 6819963965,
    "LTLS": 1560000000,
    "LUCK": 354601900,
    "LUCY": 1514773893,
    "MABA": 15358819212,
    "MAGP": 9000000004,
    "MAHA": 16666000000,
    "MAIN": 2238750000,
    "MANG": 1732601828,
    "MAPA": 28504000000,
    "MAPB": 2387922900,
    "MAPI": 16600000000,
    "MARI": 5252644000,
    "MARK": 3800000310,
    "MASB": 1387737233,
    "MAXI": 9610099981,
    "MAYA": 25906179152,
    "MBAP": 1227271952,
    "MBMA": 107995419900,
    "MBSS": 1750026639,
    "MBTO": 1070000000,
    "MCAS": 867933300,
    "MCOL": 3555560000,
    "MCOR": 37540533209,
    "MDIA": 39215538400,
    "MDIY": 25190392000,
    "MDKA": 24472983771,
    "MDKI": 2530150002,
    "MDLA": 14012825000,
    "MDLN": 12533067322,
    "MDRN": 7138697999,
    "MEDC": 25136231252,
    "MEDS": 1562500000,
    "MEGA": 23247028262,
    "MEJA": 2608081058,
    "MENN": 1434052006,
    "MERI": 435132500,
    "MERK": 448000000,
    "META": 17710708194,
    "MFMI": 757581000,
    "MGLV": 1904883411,
    "MGNA": 3411044026,
    "MGRO": 3554445700,
    "MHKI": 3750000000,
    "MICE": 600000000,
    "MIDI": 33435294800,
    "MIKA": 13907481500,
    "MINA": 9843750000,
    "MINE": 4084435300,
    "MIRA": 3961452039,
    "MITI": 3750526603,
    "MKAP": 3250000000,
    "MKNT": 5500000000,
    "MKPI": 948194000,
    "MKTR": 12060428584,
    "MLBI": 2107000000,
    "MLIA": 6615000000,
    "MLPL": 15682323987,
    "MLPT": 1875000000,
    "MMIX": 4800425380,
    "MMLP": 6889134608,
    "MNCN": 15049787710,
    "MOLI": 2724036581,
    "MORA": 47774192736,
    "MPIX": 1562574308,
    "MPMX": 4386963276,
    "MPOW": 816997053,
    "MPPA": 12966640084,
    "MPRO": 9942500000,
    "MPXL": 2000014587,
    "MRAT": 428000000,
    "MREI": 517791681,
    "MSIE": 1460007754,
    "MSIN": 60676178205,
    "MSJA": 5882352900,
    "MSKY": 1994370480,
    "MSTI": 3139416200,
    "MTDL": 12276884585,
    "MTEL": 83559677444,
    "MTFN": 31842082852,
    "MTLA": 7655126330,
    "MTMH": 2068526950,
    "MTPS": 2084850829,
    "MTRA": 770000000,
    "MTSM": 232848000,
    "MTWI": 2924486639,
    "MUTU": 3142950585,
    "MYOH": 2206312500,
    "MYOR": 22358699725,
    "MYTX": 7747281949,
    "NAIK": 3329120116,
    "NANO": 4285440269,
    "NASA": 11004929322,
    "NASI": 807400000,
    "NATO": 8001111504,
    "NAYZ": 2550011472,
    "NCKL": 63098600000,
    "NELY": 2350000000,
    "NEST": 4112500000,
    "NETV": 41360517722,
    "NFCX": 666667500,
    "NICE": 6082020000,
    "NICK": 651150000,
    "NICL": 10635644907,
    "NIKL": 2523350000,
    "NINE": 2157000000,
    "NIRO": 22198871804,
    "NISP": 22715776032,
    "NOBU": 7403659460,
    "NPGF": 3240235840,
    "NRCA": 2496258344,
    "NSSS": 23801568645,
    "NTBK": 2700064877,
    "NUSA": 7700000148,
    "NZIA": 2197540705,
    "OASA": 6347220000,
    "OBAT": 680376575,
    "OBMD": 805992931,
    "OCAP": 273200000,
    "OILS": 454056563,
    "OKAS": 2373449165,
    "OLIV": 1900073314,
    "OMED": 27058850000,
    "OMRE": 2945211000,
    "OPMS": 1000000000,
    "PACK": 32370610133,
    "PADA": 3150000000,
    "PADI": 11307246524,
    "PALM": 15732874458,
    "PAMG": 625000000,
    "PANI": 18117025598,
    "PANR": 1387500000,
    "PANS": 720000000,
    "PART": 2814754144,
    "PBID": 7500000000,
    "PBRX": 21482028246,
    "PBSA": 3000000000,
    "PCAR": 1166646700,
    "PDES": 715000000,
    "PDPP": 3061341438,
    "PEGE": 2833417056,
    "PEHA": 840000000,
    "PEVE": 1765299500,
    "PGAS": 24241508196,
    "PGEO": 41899535623,
    "PGJO": 795859095,
    "PGLI": 488000000,
    "PGUN": 5737848882,
    "PICO": 568375000,
    "PIPA": 3426097190,
    "PJAA": 1599999996,
    "PJHB": 480005617,
    "PKPK": 1200000000,
    "PLAN": 896709596,
    "PLAS": 1184200000,
    "PLIN": 3550000000,
    "PMJS": 13755600000,
    "PMMP": 2588300000,
    "PMUI": 1160000000,
    "PNBN": 23837645998,
    "PNBS": 38425504906,
    "PNGO": 781250000,
    "PNIN": 4068323920,
    "PNLF": 32022073293,
    "PNSE": 797813496,
    "POLA": 3351075600,
    "POLI": 2010526400,
    "POLL": 8318823600,
    "POLU": 220500000,
    "POLY": 2495753334,
    "POOL": 2341366264,
    "PORT": 2813941985,
    "POSA": 8388870206,
    "POWR": 16087156000,
    "PPGL": 771178020,
    "PPRE": 10224271000,
    "PPRI": 1075027288,
    "PPRO": 61675671883,
    "PRAY": 13959422300,
    "PRDA": 937500000,
    "PRIM": 3393434905,
    "PSAB": 26460000000,
    "PSAT": 1482353000,
    "PSDN": 1440000000,
    "PSGO": 18850000000,
    "PSKT": 10351231636,
    "PSSI": 5417063153,
    "PTBA": 11520659250,
    "PTDU": 1500000000,
    "PTIS": 550165300,
    "PTMP": 3169200000,
    "PTMR": 1907000000,
    "PTPP": 6199897354,
    "PTPS": 2167514856,
    "PTPW": 878187500,
    "PTRO": 10086050000,
    "PTSN": 5314344000,
    "PTSP": 220808000,
    "PUDP": 659120000,
    "PURA": 6301930902,
    "PURE": 1375181505,
    "PURI": 1000000000,
    "PWON": 48159602400,
    "PYFA": 11236694833,
    "PZZA": 3021875000,
    "RAAM": 6813620000,
    "RAFI": 3128140475,
    "RAJA": 4227082500,
    "RALS": 7096000000,
    "RANC": 1564487500,
    "RATU": 2715053800,
    "RBMS": 2656212826,
    "RCCC": 787500000,
    "RDTX": 268800000,
    "REAL": 6633610151,
    "RELF": 5727832195,
    "RELI": 1800000000,
    "RGAS": 1459234110,
    "RICY": 641717510,
    "RIGS": 609130000,
    "RIMO": 45080600000,
    "RISE": 16198599990,
    "RLCO": 625000000,
    "RMKE": 4375000000,
    "RMKO": 1250000000,
    "ROCK": 1435185100,
    "RODA": 13592128209,
    "RONY": 1250000000,
    "ROTI": 6186488888,
    "RSCH": 2650000000,
    "RSGK": 929675000,
    "RUIS": 770000000,
    "RUNS": 983557875,
    "SAFE": 821207512,
    "SAGE": 8033527260,
    "SAME": 17164632545,
    "SAMF": 10250000000,
    "SAPX": 830113500,
    "SATU": 1375000000,
    "SBAT": 4752982378,
    "SBMA": 929926282,
    "SCCO": 822333600,
    "SCMA": 73970569505,
    "SCNP": 2500000000,
    "SCPI": 3600000,
    "SDMU": 2250691100,
    "SDPC": 1274000000,
    "SDRA": 14545267990,
    "SEMA": 1347258842,
    "SFAN": 1359934021,
    "SGER": 15586909438,
    "SGRO": 1818622000,
    "SHID": 1119326168,
    "SHIP": 2500000000,
    "SICO": 910077764,
    "SIDO": 30000000000,
    "SILO": 13006125000,
    "SIMA": 442589871,
    "SIMP": 15501310000,
    "SINI": 481000000,
    "SIPD": 1839102056,
    "SKBM": 1730103217,
    "SKLT": 6907405000,
    "SKRN": 7494000000,
    "SKYB": 585000000,
    "SLIS": 2463340682,
    "SMAR": 2872193366,
    "SMBR": 9932534336,
    "SMCB": 9019381973,
    "SMDM": 4772138237,
    "SMDR": 16375600000,
    "SMGA": 8750000000,
    "SMGR": 6751540089,
    "SMIL": 8751668239,
    "SMKL": 3418085290,
    "SMKM": 1253000000,
    "SMLE": 2328153048,
    "SMMA": 6367664717,
    "SMMT": 3425000000,
    "SMRA": 16508568358,
    "SMRU": 12499385782,
    "SMSM": 5758675440,
    "SNLK": 450000000,
    "SOCI": 7059000000,
    "SOFA": 1653574499,
    "SOHO": 12691682390,
    "SOLA": 3287375000,
    "SONA": 662400000,
    "SOSS": 974525743,
    "SOTS": 1000003979,
    "SOUL": 1082526223,
    "SPMA": 4100317438,
    "SPRE": 660000000,
    "SPTO": 2700000000,
    "SQMI": 15537591429,
    "SRAJ": 12238959990,
    "SRIL": 20452176844,
    "SRSN": 6020000000,
    "SRTG": 13564835000,
    "SSIA": 4705249440,
    "SSMS": 9525000000,
    "SSTM": 1170909181,
    "STAA": 10903372600,
    "STAR": 4800000602,
    "STRK": 10721835562,
    "STTP": 1310000000,
    "SUGI": 24811541414,
    "SULI": 6320776836,
    "SUNI": 2500000000,
    "SUPA": 18081906569,
    "SUPR": 1137579698,
    "SURE": 1497576771,
    "SURI": 1267075000,
    "SWAT": 3019200000,
    "SWID": 5385019201,
    "TALF": 1353435000,
    "TAMA": 1200000696,
    "TAMU": 37500000000,
    "TAPG": 19852540000,
    "TARA": 10069645750,
    "TAXI": 10223647156,
    "TAYS": 1098920000,
    "TBIG": 22656999445,
    "TBLA": 6025373372,
    "TBMS": 734680000,
    "TCID": 402133334,
    "TCPI": 5000000000,
    "TDPM": 10485050500,
    "TEBE": 1285000000,
    "TECH": 1256300000,
    "TELE": 7310929389,
    "TFAS": 1666666500,
    "TFCO": 4823076400,
    "TGKA": 918492750,
    "TGRA": 2750000000,
    "TGUK": 3547701815,
    "TIFA": 3552213000,
    "TINS": 7447753454,
    "TIRA": 588000000,
    "TIRT": 1011774750,
    "TKIM": 3113223570,
    "TLDN": 12946530200,
    "TLKM": 99062216600,
    "TMAS": 57051500000,
    "TMPO": 1058333250,
    "TNCA": 421640000,
    "TOBA": 8257402931,
    "TOOL": 2050020320,
    "TOPS": 33330000000,
    "TOSK": 4375277300,
    "TOTL": 3410000000,
    "TOTO": 10320000000,
    "TOWR": 59098103731,
    "TOYS": 1435000712,
    "TPIA": 86511545092,
    "TPMA": 3507420034,
    "TRAM": 49643627934,
    "TRGU": 7945412700,
    "TRIL": 1200000000,
    "TRIM": 7109300000,
    "TRIN": 4551457789,
    "TRIO": 26007494645,
    "TRIS": 3141443831,
    "TRJA": 1510200000,
    "TRON": 2937439448,
    "TRST": 2808000000,
    "TRUE": 7571107860,
    "TRUK": 435000000,
    "TRUS": 800000000,
    "TSPC": 4509864300,
    "TUGU": 3555575600,
    "TYRE": 3480581727,
    "UANG": 1210000000,
    "UCID": 4156572300,
    "UDNG": 1750040072,
    "UFOE": 2898261693,
    "ULTJ": 10398175200,
    "UNIC": 383331363,
    "UNIQ": 3138983000,
    "UNIT": 75422200,
    "UNSP": 2500162344,
    "UNTD": 6666666700,
    "UNTR": 3730135136,
    "UNVR": 38150000000,
    "URBN": 3232122640,
    "UVCR": 2000144838,
    "VAST": 3055737049,
    "VERN": 4765648183,
    "VICI": 6708000000,
    "VICO": 15217075658,
    "VINS": 1553430759,
    "VISI": 3075000000,
    "VIVA": 16464270400,
    "VKTR": 43750000000,
    "VOKS": 4155602595,
    "VRNA": 5687353997,
    "VTNY": 4875160740,
    "WAPO": 1240923111,
    "WBSA": 1800000000,
    "WEGE": 9572000000,
    "WEHA": 1460554819,
    "WGSH": 2085000000,
    "WICO": 2393710348,
    "WIDI": 1600031683,
    "WIFI": 5308549015,
    "WIIM": 2099873760,
    "WIKA": 39873063858,
    "WINE": 678000000,
    "WINR": 5235316030,
    "WINS": 4460988262,
    "WIRG": 11938622394,
    "WMPP": 29406022875,
    "WMUU": 12941176500,
    "WOMF": 3481481480,
    "WOOD": 6437500000,
    "WOWS": 2475720000,
    "WSBP": 56780478486,
    "WSKT": 28806807016,
    "WTON": 8715466600,
    "YELO": 1912774405,
    "YOII": 1041867500,
    "YPAS": 668000089,
    "YULE": 1785000000,
    "YUPI": 854448900,
    "ZATA": 1700000000,
    "ZBRA": 2510706263,
    "ZINC": 25250000000,
    "ZONE": 870171478,
    "ZYRX": 1333334556,
}

def load_listed_shares(listed_file: str = 'Listed_share.xlsx') -> dict:
    """
    Return dict {kode_saham: tradeble_shares} dari data embedded (Listed_share.xlsx).
    Data 959 emiten BEI sudah di-embed langsung ke dalam kode ini —
    tidak perlu file eksternal.
    Jika file eksternal tersedia, data file akan di-merge/override data embedded.
    """
    result = dict(_LISTED_SHARES_EMBEDDED)  # copy dari embedded data

    # Coba juga baca dari file eksternal jika ada (opsional, untuk update data)
    import sys
    fname = os.path.basename(listed_file)
    candidate_dirs = []
    try:
        candidate_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    try:
        candidate_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    candidate_dirs.append(os.getcwd())
    candidates = [listed_file] + [os.path.join(d, fname) for d in candidate_dirs]
    resolved = next((p for p in candidates if os.path.exists(p)), None)
    if resolved:
        try:
            df_ls = pd.read_excel(resolved)
            df_ls.columns = df_ls.columns.str.strip()
            kode_col = next((c for c in df_ls.columns if c.lower().replace(' ','') in ('kodesaham','kode')), None)
            shares_col = next((c for c in df_ls.columns if any(kw in c.lower().replace(' ','') for kw in ('tradeble','tradeable','shares','totalshares','totalsaham'))), None)
            if kode_col and shares_col:
                df_ls[kode_col] = df_ls[kode_col].astype(str).str.strip().str.upper().str.replace('.JK','',regex=False)
                df_ls[shares_col] = pd.to_numeric(df_ls[shares_col].astype(str).str.replace(',','',regex=False), errors='coerce').fillna(0).astype(int)
                result.update(dict(zip(df_ls[kode_col], df_ls[shares_col])))
        except Exception:
            pass

    return result


def load_data_auto():
    import sys
    # Cari FreeFloat.xlsx: coba direktori script (sys.argv[0]) lalu cwd
    _ff_name = 'FreeFloat.xlsx'
    _ff_dirs = []
    try:
        _ff_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    try:
        _ff_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    _ff_dirs.append(os.getcwd())
    _ff_candidates = [_ff_name] + [os.path.join(d, _ff_name) for d in _ff_dirs]
    file_name = next((p for p in _ff_candidates if os.path.exists(p)), _ff_name)
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
                # ── v31: Total Saham — prioritas dari Listed_share.xlsx ──
                # Listed_share.xlsx berisi 'Tradeble Shares' (total saham beredar dalam lembar)
                # untuk seluruh emiten BEI. Ini digunakan untuk menghitung:
                #   - Float Lot Est  = (Free Float% / 100) * Total Saham / 100 (konversi ke lot)
                #   - % Float Swept 5D = (AvgVol5D * 5) / Float Lot Est * 100
                listed_shares_dict = load_listed_shares('Listed_share.xlsx')
                if listed_shares_dict:
                    df['Total Saham'] = df['Kode Saham'].map(listed_shares_dict).fillna(0).astype(int)
                elif 'Total Saham' in df.columns:
                    df['Total Saham'] = pd.to_numeric(
                        df['Total Saham'].astype(str).str.replace(',', '', regex=False),
                        errors='coerce'
                    ).fillna(0).astype(int)
                else:
                    df['Total Saham'] = 0
                return df, file_name
        except Exception as e:
            st.error(f"Gagal membaca file {file_name}: {e}")

    # Mode tanpa FreeFloat.xlsx: coba muat seluruh emiten dari Listed_share.xlsx
    listed_shares_dict = load_listed_shares('Listed_share.xlsx')
    if listed_shares_dict:
        default_data = pd.DataFrame({
            'Kode Saham': list(listed_shares_dict.keys()),
            'Free Float': [0.0] * len(listed_shares_dict),
            'Total Saham': list(listed_shares_dict.values()),
        })
        return default_data, "Listed_share.xlsx (tanpa Free Float)"

    default_data = pd.DataFrame({
        'Kode Saham': ['WINS', 'CNKO', 'KOIN'],
        'Free Float': [30.0, 45.0, 20.0],
        'Total Saham': [0, 0, 0],
    })
    return default_data, "Default Mode"

df_emiten, loaded_file = load_data_auto()

# ── Cek status Listed_share.xlsx ──
_listed_shares_status = load_listed_shares('Listed_share.xlsx')
_has_listed = bool(_listed_shares_status)
_n_listed   = len(_listed_shares_status)

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

def style_value(val):
    try:
        num = float(val)
        if num >= 50e9:  return 'background-color: #00cc00; color: white; font-weight: bold'
        if num >= 10e9:  return 'background-color: #66ff66;'
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
def detect_bearish_divergence(close: pd.Series, mfi_series: pd.Series, window: int = 20) -> bool:
    """
    Deteksi Bearish Divergence v25 — diperbaiki dari v13 yang terlalu sensitif.

    Masalah v13 (window=10): men-flag 100% saham sebagai divergence karena ambang batas
    terlalu longgar — setiap Higher High kecil + MFI turun 1 poin sudah dianggap divergence.

    Perbaikan v25:
      1. Window diperlebar ke 20 hari (dari 10) → konteks lebih panjang, lebih selektif
      2. Harga HARUS dekat dengan high window (dalam 5%) → divergence hanya relevan saat
         saham sudah di zona resistance, bukan masih jauh di bawahnya
      3. Price Higher High harus signifikan (>2%) → bukan sekadar 1 tick lebih tinggi
      4. MFI Lower High harus signifikan (>5 poin) → bukan sekadar noise fluktuasi normal

    Target: dari 511 saham, hanya ~5–15% yang benar-benar divergence kuat dan relevan.
    """
    if len(close) < window + 1 or len(mfi_series) < window + 1:
        return False

    c_window = close.iloc[-window:]
    m_window = mfi_series.iloc[-window:]

    # Syarat baru 1: harga saat ini harus dekat dengan high window (dalam 5%)
    # Kalau masih jauh dari high, divergence belum relevan — saham masih punya ruang naik
    current_price  = float(c_window.iloc[-1])
    window_high    = float(c_window.max())
    dist_from_high = (current_price / window_high - 1) * 100
    if dist_from_high < -5.0:
        return False

    c_max_idx = c_window.idxmax()
    c_prev    = c_window[c_window.index < c_max_idx]
    if c_prev.empty:
        return False
    c_prev_max = c_prev.max()

    # Syarat baru 2: price Higher High harus signifikan >2%
    price_gain_pct = (float(c_window[c_max_idx]) / float(c_prev_max) - 1) * 100
    price_hh       = price_gain_pct > 2.0

    m_at_c_max = m_window.loc[c_max_idx] if c_max_idx in m_window.index else m_window.iloc[-1]
    m_prev_idx = c_prev.idxmax()
    m_at_prev  = m_window.loc[m_prev_idx] if m_prev_idx in m_window.index else m_window.iloc[0]

    # Syarat baru 3: MFI Lower High harus signifikan >5 poin (bukan noise)
    mfi_drop = float(m_at_prev) - float(m_at_c_max)
    mfi_lh   = mfi_drop > 5.0

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
    Returns: (squeeze_label, bb_width_pct, bb_width_pct_rank)
    - 'SQUEEZE 🔥' jika BB sangat sempit (< squeeze_pct dari harga)
    - 'Sempit'     jika BB sempit tapi belum extreme
    - 'Normal'     sisanya
    - bb_width_pct_rank: 0.0–1.0, makin besar = BB makin LEBAR relatif 50 hari terakhir
    """
    if len(close) < window + 5:
        return "Normal", 0.0, 0.5
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
        return "SQUEEZE 🔥", round(current_width * 100, 2), round(pct_rank, 3)
    elif pct_rank <= 0.25:
        return "Sempit", round(current_width * 100, 2), round(pct_rank, 3)
    else:
        return "Normal", round(current_width * 100, 2), round(pct_rank, 3)


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
    # v32: parameter mode 1 minggu (opsional, default off)
    shortterm_mode: bool = False,
    last_mfi: float = 0.0,
    mfi_change_5d: float = 0.0,
    dist_20high: float = -99.0,
    was_score: int = 0,
) -> bool:
    """
    Kandidat Silent Accumulation:
    - Lolos volume minimum yang lebih rendah (bukan filter utama)
    - Skor silent >= threshold
    - Minimal 1 dari: BB Squeeze ATAU OBV Rising ATAU Vol Trend >= 1.2
    - Tidak divergence, tidak overbought

    v32 — Mode 1 Minggu (shortterm_mode=True):
    Filter tambahan berbasis backtesting hits vs misses:
    - MFI (14D) > 65  (hits avg 77 vs misses 61)
    - MFI Change 5D > 10  (hits avg 19 vs misses 6)
    - Dist to 20D High > -15%  (hits avg -11.6% vs misses -16.2%)
    - WAS >= 6  (hits avg 7.0 vs misses 5.5)
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
    if not has_key_signal:
        return False
    # v32: Filter ketat mode 1 minggu
    if shortterm_mode:
        if last_mfi <= 65:
            return False
        if mfi_change_5d <= 10:
            return False
        if dist_20high <= -15.0:
            return False
        if was_score < 6:
            return False
    return True

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
    return

def style_remora(val):
    """Styling untuk kolom Remora Score."""
    try:
        n = float(val)
        if n >= 8: return "background-color: #6a0dad; color: white; font-weight:bold"
        if n >= 6: return "background-color: #1a6e1a; color: white; font-weight:bold"
        if n >= 4: return "background-color: #e67e22; color: white"
    except Exception:
        pass
    return ""

def style_remora_label(val):
    """Styling untuk kolom Remora Label."""
    v = str(val)
    if "PRIME"  in v: return "background-color: #6a0dad; color: white; font-weight:bold"
    if "KUAT"   in v: return "background-color: #1a6e1a; color: white; font-weight:bold"
    if "PANTAU" in v: return "background-color: #e67e22; color: white"
    return ""

def style_moonstock_score(val):
    """Styling untuk kolom Moonstock Score."""
    try:
        n = float(val)
        if n >= 5: return 'background-color: #c0392b; color: white; font-weight: bold'
        if n >= 4: return 'background-color: #e67e22; color: white; font-weight: bold'
    except Exception:
        pass
    return ''

def compute_remora_score(row):
    """
    Remora Score (0–10) — gabungan kriteria float + akumulasi.
    Bisa dipanggil dari mana saja (top-level function).
    """
    score = 0
    ff = row.get('Free Float (%)', 0)
    if 0 < ff < 15:
        score += 2
    elif 0 < ff < 25:
        score += 1
    accel = 0.0
    try:
        accel = float(row.get('Vol Accel (5D/20D)', 0))
    except Exception:
        pass
    if accel >= 3.0:
        score += 2
    elif accel >= 2.0:
        score += 1
    if str(row.get('OBV Trend', '')).startswith('Rising'):
        score += 1
    if 'SQUEEZE' in str(row.get('BB Squeeze', '')):
        score += 1
    try:
        if float(row.get('Price Tightness (%)', 99)) < 3.0:
            score += 1
    except Exception:
        pass
    try:
        if float(row.get('Silent Score', 0)) >= 6:
            score += 1
    except Exception:
        pass
    try:
        if float(row.get('WAS', 0)) >= 7:
            score += 1
    except Exception:
        pass
    wyckoff_phase = str(row.get('Wyckoff Phase', ''))
    if 'Akumulasi' in wyckoff_phase or 'Spring' in wyckoff_phase:
        score += 1
    if 'Bearish' in str(row.get('Divergence Warning', '')):
        score -= 1
    try:
        if float(row.get('Rel Vol (20D)', 0)) > 5.0:
            score -= 1
    except Exception:
        pass
    try:
        if float(row.get('Dist to 20D High (%)', -99)) > -5.0:
            score -= 1
    except Exception:
        pass
    return max(0, min(score, 10))

def remora_label(score):
    """Label teks untuk Remora Score."""
    if score >= 8: return "🔥 PRIME"
    if score >= 6: return "✅ KUAT"
    if score >= 4: return "👀 PANTAU"
    return "⬜ LEMAH"


# ─────────────────────────────────────────────
# 5g. ENTRY READINESS — v23 Coil Watch
# ─────────────────────────────────────────────

def calc_entry_readiness(row):
    """
    Entry Readiness Score (0-5): seberapa banyak trigger nyata yang sudah muncul.
    +1  Volume Spike 20D : Rel Vol (20D) > 2.0x
    +1  MFI Lonjak       : MFI Change 5D > 10
    +1  MFI Kuat         : MFI (14D) > 65
    +1  Vol Spike Hari Ini: Vol Spike Today > 2.0x ADV20
    +1  Dekat Breakout   : Dist to 20D High > -5%  (v32: diperketat dari -1%)
    """
    score = 0
    try:
        if float(row.get('Rel Vol (20D)', 0)) > 2.0:
            score += 1
    except Exception:
        pass
    try:
        if float(row.get('MFI Change 5D', 0)) > 10:
            score += 1
    except Exception:
        pass
    try:
        if float(row.get('MFI (14D)', 0)) > 65:
            score += 1
    except Exception:
        pass
    try:
        if float(row.get('Vol Spike Today (x ADV20)', 0)) > 2.0:
            score += 1
    except Exception:
        pass
    try:
        if float(row.get('Dist to 20D High (%)', -99)) > -5.0:
            score += 1
    except Exception:
        pass
    return score


def entry_readiness_label(v):
    """Label teks untuk Entry Readiness Score (v32: skala 0-5)."""
    try:
        v = int(v)
    except Exception:
        return '⚪ Belum'
    if v >= 4: return '🟢 SIAP ENTRY'
    if v == 3: return '🟡 Hampir Siap'
    if v == 2: return '🟠 Tunggu'
    if v == 1: return '🔵 Perhatikan'
    return '⚪ Belum'


def style_entry_readiness(v):
    """Warna kolom Entry Readiness Score."""
    try:
        v = int(v)
    except Exception:
        return ''
    if v >= 4: return 'background-color:#27ae60;color:white;font-weight:bold'
    if v == 3: return 'background-color:#2ecc71;color:white;font-weight:bold'
    if v == 2: return 'background-color:#f39c12;color:black'
    if v == 1: return 'background-color:#3498db;color:white'
    return 'background-color:#95a5a6;color:white'
''

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

@st.cache_data(ttl=60)   # refresh setiap 1 menit
def fetch_live_signals(ticker_jk: str, end_date=None):
    """Ambil data untuk Live Signal Panel.
    BACKTEST FIX: jika end_date diisi, data dipotong s.d. tanggal tersebut.
    """
    try:
        if end_date is not None:
            start = pd.Timestamp(end_date) - timedelta(days=90)
            end_excl = pd.Timestamp(end_date) + timedelta(days=1)
            df = yf.download(ticker_jk, start=start, end=end_excl, progress=False, auto_adjust=True)
            if not df.empty:
                df = df[df.index <= pd.Timestamp(end_date)]
        else:
            df = yf.download(ticker_jk, period="60d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


def show_live_signal_panel(ticker_code: str, end_date=None):
    """Tampilkan panel sinyal live. BACKTEST FIX: data dipotong s.d. end_date jika diisi."""
    df = fetch_live_signals(ticker_code + ".JK", end_date=end_date)
    if df is None or df.empty:
        return
    c = df['Close']
    h = df['High']
    l = df['Low']
    v = df['Volume']
    o = df['Open']

    # Flatten jika masih MultiIndex
    def _s1(s):
        return s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s

    c, h, l, v, o = _s1(c), _s1(h), _s1(l), _s1(v), _s1(o)

    ma20 = float(c.rolling(20).mean().iloc[-1])
    last_price = float(c.iloc[-1])

    # Hitung ulang semua sinyal live
    candle        = detect_candlestick_pattern(o, h, l, c)
    vol_climax    = detect_volume_climax(v)
    consol_bo     = detect_consolidation_breakout(c)
    slope         = compute_trendline_slope(c)
    bb_squeeze_lbl, bb_width, _bb_pct_rank = detect_bb_squeeze(c)
    obv           = compute_obv_trend(c, v)
    vol_trend     = compute_vol_trend_ratio(v)
    tightness     = compute_price_tightness(c)

    st.markdown("#### 📡 Live Signal (diperbarui tiap 1 menit)")
    cols = st.columns(4)
    cols[0].metric("Candlestick",  candle or "-")
    cols[1].metric("Trendline",    slope)
    cols[2].metric("BB Squeeze",   bb_squeeze_lbl)
    cols[3].metric("OBV Trend",    obv)

    cols2 = st.columns(4)
    cols2[0].metric("Vol Climax",      "✅ Ya" if vol_climax else "—")
    cols2[1].metric("Consol Breakout", "✅ Ya" if consol_bo else "—")
    cols2[2].metric("Vol Trend Ratio", f"{vol_trend:.2f}x")
    cols2[3].metric(
        "Harga vs MA20",
        f"{'✅ Di atas' if last_price >= ma20 else '❌ Di bawah'} ({((last_price - ma20) / ma20 * 100):+.1f}%)"
    )

    # Visual Chart Analysis live
    visual = compute_visual_chart_analysis(o, h, l, c, v)
    st.info(f"🔍 **Visual Chart Analysis Live:** {visual}")
    st.caption(
        f"⏱️ Data: {df.index[-1].strftime('%Y-%m-%d')} | "
        f"Refresh otomatis tiap 1 menit"
    )


@st.cache_data(ttl=300)
def fetch_ohlcv_for_plotly(ticker_jk: str, end_date=None, days: int = 120):
    """Fetch OHLCV data untuk Plotly chart.
    BACKTEST FIX: pakai end_date agar chart tidak menampilkan data setelah tanggal backtest.
    """
    try:
        if end_date is not None:
            start = pd.Timestamp(end_date) - timedelta(days=days + 60)
            end_exclusive = pd.Timestamp(end_date) + timedelta(days=1)
            df = yf.download(ticker_jk, start=start, end=end_exclusive,
                             progress=False, auto_adjust=True)
            if not df.empty:
                df = df[df.index <= pd.Timestamp(end_date)]
        else:
            df = yf.download(ticker_jk, period=f"{days}d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        df = df.tail(days)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open','High','Low','Close','Volume']].copy()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA50'] = df['Close'].rolling(50).mean()
        df['Resist20'] = df['High'].rolling(20).max()
        df['Support20'] = df['Low'].rolling(20).min()
        return df
    except Exception as e:
        return None


def show_plotly_candlestick(ticker_code: str, chart_key: str = "plotly_chart", end_date=None):
    """
    Tampilkan Plotly candlestick chart interaktif dengan MA, Volume, Support/Resistance.
    """
    ticker_jk = ticker_code + ".JK"

    # ── Refresh button + timestamp ──
    col_refresh, col_ts = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh Data", key=f"refresh_{chart_key}"):
            st.cache_data.clear()
            st.rerun()
    with col_ts:
        st.caption(f"Data terakhir diambil: {pd.Timestamp.now().strftime('%H:%M:%S')}")

    with st.spinner(f"Memuat chart Plotly untuk {ticker_code}…"):
        df = fetch_ohlcv_for_plotly(ticker_jk, end_date=end_date)

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

    # ── Live Signal Panel (data TTL 1 menit) ──
    st.markdown("---")
    show_live_signal_panel(ticker_code, end_date=end_date)


# ─────────────────────────────────────────────
# 6. FUNGSI ANALISA UTAMA v16
# ─────────────────────────────────────────────
def get_signals_and_data(df_c, df_v, df_h, df_l, df_o, df_ref, min_vol_lot,
                          min_mfi_change_watch, min_early_score,
                          watch_require_outperform,
                          min_vol_silent_lot, min_silent_score,
                          min_shortlist_score=13,
                          enable_was_filter=False, min_was_score=6,
                          enable_wyckoff_path=True,
                          min_was_ss_base=6, min_was_silent=6, min_was_adx=50,
                          shortterm_mode=False,
                          start_date=None):
    results = []
    shortlist_keys = []
    prebreakout_keys = []
    silent_accum_keys = []
    gemini_shortlist_keys = []   # ── v37: Shortlist Gemini (replika rule Gemini, hard filter apa adanya) ──
    skip_log = []   # ── v35 DEBUG: catat kenapa saham gugur dari hasil ──
    min_vol_lembar = min_vol_lot * 100
    min_vol_silent_lembar = min_vol_silent_lot * 100
    ff_lookup = dict(zip(df_ref['Kode Saham'], df_ref['Free Float']))
    ts_lookup = dict(zip(df_ref['Kode Saham'], df_ref.get('Total Saham', pd.Series(0, index=df_ref.index))))

    ihsg_c = df_c["^JKSE"].dropna() if "^JKSE" in df_c.columns else pd.Series()
    ihsg_perf = ((ihsg_c.iloc[-1] - ihsg_c.iloc[-20]) / ihsg_c.iloc[-20]
                 if len(ihsg_c) >= 20 else 0)

    for col in df_c.columns:
        if col == "^JKSE" or col == "" or pd.isna(col):
            continue

        _code_dbg = str(col).replace(".JK", "").upper()

        c = df_c[col].dropna()
        v = df_v[col].dropna()
        h = df_h[col].dropna()
        l = df_l[col].dropna()
        # Open series (untuk candlestick pattern detection)
        o_col = df_o[col].dropna() if col in df_o.columns else pd.Series(dtype=float)

        if len(c) < 55:
            skip_log.append({
                "Kode": _code_dbg,
                "Alasan": f"Data historis kurang ({len(c)} baris valid, butuh ≥55)",
            })
            continue

        # ── Volume filter ──
        # Gunakan min_vol_silent_lembar sebagai floor absolut agar saham low-cap tetap masuk proses
        avg_vol20 = v.rolling(20).mean().iloc[-1]
        avg_vol50 = v.rolling(50).mean().iloc[-1]
        if avg_vol20 < min_vol_silent_lembar:   # filter paling longgar (silent threshold)
            skip_log.append({
                "Kode": _code_dbg,
                "Alasan": (f"Avg Vol 20D = {avg_vol20/100:,.0f} lot < ambang Silent "
                           f"{min_vol_silent_lot:,.0f} lot"),
            })
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
        rsi_series = ta.momentum.RSIIndicator(close=c, window=14).rsi()
        last_rsi = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else 50.0

        # ── ADX + DI+ / DI- ──
        try:
            _adx_ind  = ta.trend.ADXIndicator(high=h, low=l, close=c, window=14)
            _adx_vals = _adx_ind.adx()
            _dmp_vals = _adx_ind.adx_pos()
            _dmn_vals = _adx_ind.adx_neg()
            last_adx  = float(_adx_vals.iloc[-1])
            last_dmp  = float(_dmp_vals.iloc[-1])
            last_dmn  = float(_dmn_vals.iloc[-1])

            adx_direction  = "Bullish (DI+>DI-)" if last_dmp > last_dmn else "Bearish (DI->DI+)"
            is_adx_bullish = last_dmp > last_dmn

            adx_prev3 = float(_adx_vals.iloc[-4:-1].mean())
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
        except Exception:
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

        # ── v37: SHORTLIST GEMINI — replika PERSIS rule screener Gemini (2P & 7P) ──
        # Ini SENGAJA dibuat sebagai hard filter apa adanya (bukan skoring bertingkat
        # seperti shortlist utama), supaya karakter "float kecil + breakout dini" yang
        # terbukti profitable di screener sederhana tidak ikut ter-encer oleh syarat
        # tambahan (ADX bullish wajib, threshold skor tinggi, dsb).
        ma5   = c.rolling(5).mean().iloc[-1]
        ma50  = c.rolling(50).mean().iloc[-1]
        vol_ma5  = v.rolling(5).mean().iloc[-1]
        vol_ma20 = avg_vol20  # sudah dihitung di atas sebagai v.rolling(20).mean()
        _last_price = c.iloc[-1]
        _last_vol   = v.iloc[-1]

        _gemini_common_ok = bool(
            _last_price > 50
            and vol_ma5 > 50000
            and ma20 > 0 and ma50 > 0
            and _last_price <= 1.01 * ma20
            and ma20 >= 1.0 * ma50
            and _last_price >= 0.98 * ma50
        )
        # Screener "2 Parameter": volume hari ini > 1.2x Volume MA5, Free Float <= 40%
        gemini2_ok = bool(
            _gemini_common_ok
            and _last_vol > 1.2 * vol_ma5
            and 0 < free_float <= 40
        )
        # Screener "7 Parameter": Volume MA5 > Volume MA20, Free Float < 40%,
        # Price MA5 < Price MA20 (harga baru mulai naik dari bawah MA20)
        gemini7_ok = bool(
            _gemini_common_ok
            and vol_ma5 > 1.0 * vol_ma20
            and 0 < free_float < 40
            and ma5 < 1.0 * ma20
        )
        is_gemini_shortlist = gemini2_ok or gemini7_ok
        _gemini_path = []
        if gemini2_ok:
            _gemini_path.append("Gemini-2P")
        if gemini7_ok:
            _gemini_path.append("Gemini-7P")
        gemini_rule_match = " + ".join(_gemini_path)

        if is_gemini_shortlist:
            gemini_shortlist_keys.append(ticker_name)

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
        bb_squeeze_label, bb_width_pct, bb_width_pct_rank = detect_bb_squeeze(c, window=20)
        obv_trend_label   = compute_obv_trend(c, v, lookback=10)
        vol_trend_ratio   = compute_vol_trend_ratio(v, short=5, long=20)
        price_tightness   = compute_price_tightness(c, lookback=10)
        avg_vol20_lot     = avg_vol20 / 100

        # ── v29: Float Analysis (Hitung Barang) — ditempatkan setelah avg_vol20_lot ──
        total_shares    = int(ts_lookup.get(ticker_name, 0))
        avg_vol5_lot    = float(v.tail(5).mean()) / 100
        vol5_sum_lot    = float(v.tail(5).sum()) / 100
        _float_analysis = compute_float_analysis(
            free_float_pct = free_float,
            avg_vol20_lot  = avg_vol20_lot,
            avg_vol5_lot   = avg_vol5_lot,
            total_shares   = total_shares,
            vol5_sum_lot   = vol5_sum_lot,
        )

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

        # ── v27: WYCKOFF ACCUMULATION SCORE (WAS) — dihitung sebelum shortlist ──
        _was_score, _was_reasons = compute_wyckoff_accumulation_score(
            silent_score    = silent_score,
            price_tightness = price_tightness,
            obv_trend       = obv_trend_label,
            free_float      = free_float,
            last_adx        = last_adx,
            is_adx_bullish  = is_adx_bullish,
            last_mfi        = last_mfi,
            mfi_change_5d   = mfi_change_5d,
            is_above_ma20   = is_above_ma20,
            has_bearish_div = has_bearish_div,
        )

        # ── SHORTLIST LOGIC v25 — Data-Driven Scoring Model ──
        #
        # Dibangun dari backtesting 511 saham vs top gainer 6 & 7 Mei 2026 (n=63 winner).
        # Pendekatan berubah: dari filter boolean ketat → scoring berbasis hit-rate aktual.
        #
        # SCORING MODEL (maks ~17 poin):
        #
        # [ADX Zone]  hit-rate aktual:
        #   ADX ≥ 35              → +3  (hit 19%)
        #   ADX 20–35             → +2  (hit 20%)
        #   ADX 15–20             → +1  (hit 11%)
        #   ADX < 15              → 0   (hit 3%,  sangat lemah)
        #
        # [Dist to 20D High]  semakin jauh dari resistance = lebih baik:
        #   Dist ≤ −25%           → +3  (hit 23–29%)
        #   Dist −25% s/d −15%   → +2  (hit 16%)
        #   Dist −15% s/d −10%   → +1  (hit 9%)
        #   Dist > −10%           → 0   (dekat resistance, hit < 8%)
        #
        # [MFI Level]  momentum uang masuk:
        #   MFI ≥ 75              → +2  (hit 15%)
        #   MFI 55–75             → +1  (hit 12%)
        #
        # [MFI Change 5D]  U-shape: ekstrem positif DAN negatif sama-sama baik:
        #   |MFI Change| ≥ 20     → +2  (hit 18–21%)
        #   MFI Change ≥ 10       → +1  (hit 11%)
        #
        # [Vol Trend Ratio]  volume spike sangat prediktif:
        #   VolTrend ≥ 2.0        → +2  (hit 22%)
        #   VolTrend ≤ 0.8        → +1  (kontraksi volume = diam-diam, hit 15%)
        #
        # [ADX Direction]  Bullish DI+ > DI-:
        #   Bullish               → +1  (hit 14% vs 9% Bearish)
        #
        # [OBV Trend]  akumulasi tersembunyi:
        #   Rising ↑              → +1  (hit 12% vs 13% Falling — lemah tapi konsisten)
        #
        # [Market RS]  outperform IHSG:
        #   Outperform            → +1  (hit 12% vs 12% — slight edge)
        #
        # [BB Squeeze]  energi terkompresi:
        #   SQUEEZE 🔥            → +1  (bonus sinyal akumulasi)
        #
        # [Bearish Divergence]  BUKAN eliminasi — hanya pengurang skor:
        #   Divergence terdeteksi → −1  (soft penalty, bukan hard eliminasi)
        #   (Data: divergence hit-rate 14%, lebih tinggi dari non-divergence → tidak valid
        #    sebagai filter eliminasi. Fungsi telah diperbaiki di v25 agar lebih presisi.)
        #
        # TARGET: threshold 10 → ~54 saham, hit-rate ~31%; threshold 11 → ~23 saham, hit 39%
        # Dengan Min ADX Direction Bullish WAJIB → lebih selektif

        shortlist_score = 0
        shortlist_reasons_v25 = []

        # ADX Zone
        if last_adx >= 35:
            shortlist_score += 3
            shortlist_reasons_v25.append(f"ADX {last_adx:.0f}≥35 (+3)")
        elif last_adx >= 20:
            shortlist_score += 2
            shortlist_reasons_v25.append(f"ADX {last_adx:.0f} 20-35 (+2)")
        elif last_adx >= 15:
            shortlist_score += 1
            shortlist_reasons_v25.append(f"ADX {last_adx:.0f} 15-20 (+1)")

        # Dist to 20D High
        if dist_20high <= -25.0:
            shortlist_score += 3
            shortlist_reasons_v25.append(f"Dist {dist_20high:.0f}%≤-25 (+3)")
        elif dist_20high <= -15.0:
            shortlist_score += 2
            shortlist_reasons_v25.append(f"Dist {dist_20high:.0f}% (+2)")
        elif dist_20high <= -10.0:
            shortlist_score += 1
            shortlist_reasons_v25.append(f"Dist {dist_20high:.0f}% (+1)")

        # MFI Level
        if last_mfi >= 75:
            shortlist_score += 2
            shortlist_reasons_v25.append(f"MFI {last_mfi:.0f}≥75 (+2)")
        elif last_mfi >= 55:
            shortlist_score += 1
            shortlist_reasons_v25.append(f"MFI {last_mfi:.0f} (+1)")

        # MFI Change (U-shape)
        if abs(mfi_change_5d) >= 20:
            shortlist_score += 2
            shortlist_reasons_v25.append(f"MFI chg {mfi_change_5d:+.0f} extreme (+2)")
        elif mfi_change_5d >= 10:
            shortlist_score += 1
            shortlist_reasons_v25.append(f"MFI chg {mfi_change_5d:+.0f} (+1)")

        # Vol Trend Ratio
        if vol_trend_ratio >= 2.0:
            shortlist_score += 2
            shortlist_reasons_v25.append(f"VolTrend {vol_trend_ratio:.1f}x spike (+2)")
        elif vol_trend_ratio <= 0.8:
            shortlist_score += 1
            shortlist_reasons_v25.append(f"VolTrend {vol_trend_ratio:.1f}x kontraks (+1)")

        # ADX Direction
        if is_adx_bullish:
            shortlist_score += 1
            shortlist_reasons_v25.append("DI+>DI- (+1)")

        # OBV Trend
        if obv_trend_label == "Rising ↑":
            shortlist_score += 1
            shortlist_reasons_v25.append("OBV Rising (+1)")

        # Market RS
        if rs == "Outperform":
            shortlist_score += 1
            shortlist_reasons_v25.append("RS Outperform (+1)")

        # BB Squeeze bonus
        if bb_squeeze_label == "SQUEEZE 🔥":
            shortlist_score += 1
            shortlist_reasons_v25.append("BB Squeeze (+1)")

        # Bearish Divergence — soft penalty only (bukan eliminasi)
        if has_bearish_div:
            shortlist_score -= 1
            shortlist_reasons_v25.append("⚠️ Divergence (-1)")

        # ── WYCKOFF PHASE DETECTOR (v26) — dihitung sebelum shortlist ─────────
        # Phase A — Selling Climax
        _phase_a   = detect_phase_a_selling_climax(c, v, h, l, lookback=60)
        _had_sc    = _phase_a["had_sc"]

        # Phase C — Spring (low-volume classic)
        _sr        = compute_support_resistance(h, l, c, n=20)
        _spring    = detect_phase_c_spring(c, v, l, _sr["support"])

        # Phase C — Shakeout Agresif (v33)
        _shakeout  = detect_shakeout_aggressive(c, o_col, h, l, v, support_level=_sr["support"])
        _shakeout_detected  = _shakeout["detected"]
        _shakeout_strength  = _shakeout["strength"]
        _shakeout_type      = _shakeout["shakeout_type"]

        # ── v32: Vol Spike Hari Ini & Gap to R1 ──
        _vol_today       = float(v.iloc[-1])
        _vol_spike_today = round(_vol_today / (avg_vol20 if avg_vol20 > 0 else 1), 2)
        _resistance_r1   = _sr["resistance"]
        _gap_to_r1_pct   = round((_resistance_r1 / c.iloc[-1] - 1) * 100, 2) if (_resistance_r1 and c.iloc[-1] > 0) else 0.0
        _is_spring = _spring["is_spring"]

        # Composite Wyckoff Sequence Score
        _w_score, _w_reasons = compute_wyckoff_sequence_score(
            had_sc            = _had_sc,
            sc_days_ago       = _phase_a["sc_days_ago"],
            silent_score      = silent_score,
            price_tightness   = price_tightness,
            obv_trend         = obv_trend_label,
            is_spring         = _is_spring,
            spring_strength   = _spring["strength"],
            is_breakout       = is_breakout,
            rel_vol_20        = rel_vol_20,
            adx_trend         = adx_trend,
            is_adx_bullish    = is_adx_bullish,
            free_float        = free_float,
            vol_trend_ratio   = vol_trend_ratio,
            shakeout_detected = _shakeout_detected,
            shakeout_strength = _shakeout_strength,
            shakeout_score    = _shakeout["score"],
        )
        _w_label = wyckoff_phase_label(
            _w_score, _is_spring, is_breakout, silent_score, _had_sc,
            shakeout_detected=_shakeout_detected, shakeout_strength=_shakeout_strength,
        )
        # ─────────────────────────────────────────────────────────────────────

        # WAJIB: ADX Direction Bullish — satu-satunya hard filter yang terbukti valid
        adx_bull_required = is_adx_bullish

        # WAJIB: volume utama
        vol_required = passes_main_vol

        # ── DUAL-PATH SHORTLIST v28 ──────────────────────────────────────────
        #
        # Jalur 1 — Momentum (Shortlist Score tinggi):
        #   SS >= min_shortlist_score (default 13)
        #   Menangkap saham yang sudah menunjukkan momentum terukur
        #
        # Jalur 2 — Wyckoff Accumulation (opsional, default ON):
        #   WAS >= 9  (akumulasi bandar sangat kuat — 6 faktor Wyckoff)
        #   SS  >= 6  (minimal ada sinyal teknikal)
        #   Silent >= 6  (akumulasi tersembunyi terdeteksi)
        #   ADX >= 50  (tren sangat kuat di balik konsolidasi)
        #   Phase B/C/SC  (konfirmasi Wyckoff)
        #   Above MA20  (struktur harga masih sehat)
        #   Price Tightness < 4%  (harga dikunci ketat)
        #   OBV Rising  (smart money masuk diam-diam)
        #
        # Hasil: ~15–20 saham, termasuk BSBK-type yang terbang setelah akumulasi

        _phase_b_or_c = ("Akumulasi" in _w_label or "Spring" in _w_label or "SC" in _w_label or "Shakeout" in _w_label)

        jalur1_ok = (shortlist_score >= min_shortlist_score)

        jalur2_ok = (
            enable_wyckoff_path
            and _was_score >= min_was_score
            and shortlist_score >= min_was_ss_base
            and silent_score >= min_was_silent
            and last_adx >= min_was_adx
            and _phase_b_or_c
            and is_above_ma20 == "YA"
            and price_tightness < 4.0
            and obv_trend_label == "Rising ↑"
        )

        is_shortlist = vol_required and adx_bull_required and (jalur1_ok or jalur2_ok)

        # FIX: "Jalur Masuk" harus konsisten dengan is_shortlist (keanggotaan shortlist
        # sesungguhnya). Sebelumnya label ini diisi hanya berdasarkan jalur1_ok/jalur2_ok,
        # tanpa mensyaratkan vol_required & adx_bull_required — akibatnya saham yang TIDAK
        # lolos shortlist tetap tampil berlabel jalur masuk di sheet "Semua Analisa",
        # sehingga tidak sinkron dengan kolom "Ada di Shortlist" di file backtest.
        shortlist_entry_path = ""
        if is_shortlist:
            if jalur1_ok and jalur2_ok:
                shortlist_entry_path = "Momentum + Wyckoff"
            elif jalur1_ok:
                shortlist_entry_path = "Momentum (SS)"
            elif jalur2_ok:
                shortlist_entry_path = "🧲 Wyckoff Accum"
        # ─────────────────────────────────────────────────────────────────────

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
                shortterm_mode    = shortterm_mode,
                last_mfi          = last_mfi,
                mfi_change_5d     = mfi_change_5d,
                dist_20high       = dist_20high,
                was_score         = _was_score,
            )
        )

        if is_watch:
            prebreakout_keys.append(ticker_name)
        if is_silent:
            silent_accum_keys.append(ticker_name)

        # ── v35: Agregasi Rentang Tanggal (jika user pilih 2 tanggal) ──
        _period_vol_lot          = '-'
        _period_value_rp         = '-'
        _period_up_days          = '-'
        _period_down_days        = '-'
        _period_price_change_pct = '-'
        if start_date is not None:
            _start_ts     = pd.Timestamp(start_date)
            _mask_period  = c.index >= _start_ts
            _c_period     = c[_mask_period]
            _v_period     = v.reindex(c.index)[_mask_period]  # jaga alignment tanggal dgn c
            if len(_c_period) >= 1:
                _period_vol_lot  = float(_v_period.sum() / 100)
                _period_value_rp = float((_v_period * _c_period).sum())
                _c_diff = _c_period.diff().dropna()
                _period_up_days   = int((_c_diff > 0).sum())
                _period_down_days = int((_c_diff < 0).sum())
                _period_price_change_pct = (
                    round((_c_period.iloc[-1] - _c_period.iloc[0]) / _c_period.iloc[0] * 100, 2)
                    if _c_period.iloc[0] > 0 else 0.0
                )

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
            'Value (Rp)':            float(v.iloc[-1] * c.iloc[-1]),
            # ── v35: Kolom agregat rentang tanggal (isi '-' kalau mode 1 tanggal) ──
            'Volume Periode (Lot)':       _period_vol_lot,
            'Value Periode (Rp)':         _period_value_rp,
            'Hari Naik (Periode)':        _period_up_days,
            'Hari Turun (Periode)':       _period_down_days,
            'Perubahan Harga Periode (%)': _period_price_change_pct,
            'Rel Vol (20D)':         float(rel_vol_20),
            'Rel Vol (50D)':         float(rel_vol_50),
            'Consec Up Days':        consecutive_up,
            'AvgVol20 (Lot)':        int(avg_vol20 / 100),
            'Early Momentum Score':  early_score,
            'Pre-Breakout Watch':    '🔭 Watch' if is_watch else '',
            # V18: Silent Accumulation columns
            'BB Squeeze':            bb_squeeze_label,
            'BB Width (%)':          bb_width_pct,
            'BB Width Pct Rank':     bb_width_pct_rank,
            'OBV Trend':             obv_trend_label,
            'Vol Trend Ratio':       vol_trend_ratio,
            'Price Tightness (%)':   price_tightness,
            'Silent Score':          silent_score,
            'Silent Accum':          '🕵️ Silent' if is_silent else '',
            'Composite Rank':        comp_rank,
            'Composite Criteria':    " | ".join(comp_criteria),
            'Shortlist Score':        shortlist_score,
            'Shortlist Reasons':     ", ".join(shortlist_reasons_v25) if shortlist_reasons_v25 else "",
            'Chart Analysis':        chart_analysis,
            'Visual Chart Analysis': visual_analysis,
            # ── v26: Wyckoff Phase Detector ──
            'Wyckoff Score':    _w_score,
            'Wyckoff Phase':    _w_label,
            'Wyckoff Reasons':  " | ".join(_w_reasons),
            'Spring Detected':  '🌱 Spring' if _is_spring else '',
            'Spring Strength':  _spring["strength"],
            'SC Detected':      '💥 SC' if _had_sc else '',
            'SC Vol Ratio':     _phase_a["sc_vol_ratio"],
            'SC Price Drop (%)':_phase_a["sc_price_drop_pct"],
            # ── v33: Shakeout Agresif ──
            'Shakeout Detected':  ('🔥 Kuat' if _shakeout_strength == "Kuat" else '⚡ Normal') if _shakeout_detected else '',
            'Shakeout Type':      _shakeout_type,
            'Shakeout Score':     _shakeout["score"] if _shakeout_detected else 0,
            'Shakeout Low':       _shakeout["shakeout_low"] if _shakeout_detected else 0.0,
            'Shakeout Vol Ratio': _shakeout["vol_ratio"] if _shakeout_detected else 0.0,
            'Shakeout Days Ago':  _shakeout["days_ago"] if _shakeout_detected else -1,
            # ── v33: Shakeout Context Warning ──
            'Shakeout Verdict':     '',   # diisi di bawah jika shakeout terdeteksi
            'Shakeout Confidence':  0,
            'Shakeout Warning':     '',
            # ── v27: Wyckoff Accumulation Score ──
            'WAS':              _was_score,
            'WAS Reasons':      " | ".join(_was_reasons),
            'Jalur Masuk':      shortlist_entry_path,
            # ── v29: Float Analysis (Hitung Barang) ──
            'Vol Accel (5D/20D)':      _float_analysis["vol_accel_ratio"],
            'Float Lot Est':           _float_analysis["float_lot_est"] if _float_analysis["float_lot_est"] > 0 else "-",
            'Estimasi Lot Terkumpul':  _float_analysis["accumulated_lot_est"] if _float_analysis["accumulated_lot_est"] > 0 else "-",
            '% Float Swept 5D':        _float_analysis["pct_swept_5d"] if _float_analysis["pct_swept_5d"] > 0 else "-",
            'Float Urgency':           _float_analysis["urgency"],
            'Float Note':              _float_analysis["note"],
            # ── v32: Short-Term Trigger Columns ──
            'Vol Spike Today (x ADV20)': _vol_spike_today,
            'Gap to R1 (%)':             _gap_to_r1_pct,
            # ── v37: Shortlist Gemini (replika rule screener sederhana) ──
            'Gemini Shortlist':    '🎯 Gemini' if is_gemini_shortlist else '',
            'Gemini Rule Match':   gemini_rule_match,
            'Price MA5':           float(ma5),
            'Price MA20':          float(ma20),
            'Price MA50':          float(ma50),
            'Volume MA5 (Lot)':    float(vol_ma5 / 100),
            'Volume MA20 (Lot)':   float(vol_ma20 / 100),
        })

    df_results = pd.DataFrame(results)

    # ── v33: Hitung Shakeout Context Warning untuk semua baris ──────────────
    if not df_results.empty and 'Shakeout Score' in df_results.columns:
        for idx, row in df_results.iterrows():
            if row.get('Shakeout Score', 0) > 0:
                _ctx = compute_shakeout_context_warning(
                    shakeout_score  = int(row.get('Shakeout Score', 0)),
                    wyckoff_score   = int(row.get('Wyckoff Score', 0)),
                    silent_score    = int(row.get('Silent Score', 0)),
                    obv_trend       = str(row.get('OBV Trend', '')),
                    was_score       = int(row.get('WAS', 0)),
                    adx_direction   = str(row.get('ADX Direction', '')),
                    wyckoff_phase   = str(row.get('Wyckoff Phase', '')),
                    vol_trend_ratio = float(row.get('Vol Trend Ratio', 1.0)),
                    price_tightness = float(row.get('Price Tightness (%)', 5.0)),
                    free_float      = float(row.get('Free Float (%)', 50.0)),
                )
                df_results.at[idx, 'Shakeout Verdict']    = f"{_ctx['verdict_icon']} {_ctx['verdict']}"
                df_results.at[idx, 'Shakeout Confidence'] = _ctx['confidence']
                df_results.at[idx, 'Shakeout Warning']    = " | ".join(_ctx['warnings']) if _ctx['warnings'] else "—"

    return df_results, shortlist_keys, prebreakout_keys, silent_accum_keys, skip_log, gemini_shortlist_keys

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

@st.cache_data(ttl=300)
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


@st.cache_data(ttl=300)
def fetch_ohlcv_summary(ticker_jk: str, end_date=None) -> str:
    """BACKTEST FIX: jika end_date diisi, data dipotong s.d. tanggal tersebut."""
    try:
        if end_date is not None:
            start = pd.Timestamp(end_date) - timedelta(days=150)
            end_excl = pd.Timestamp(end_date) + timedelta(days=1)
            df = yf.download(ticker_jk, start=start, end=end_excl, progress=False, auto_adjust=True)
            if not df.empty:
                df = df[df.index <= pd.Timestamp(end_date)]
        else:
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


def ai_chart_analysis(ticker_code: str, end_date=None) -> dict:
    ticker_jk = ticker_code + ".JK"
    ohlcv_text = fetch_ohlcv_summary(ticker_jk, end_date=end_date)
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
st.sidebar.header("⚙️ Konfigurasi v36")

# ── Status Listed_share.xlsx (sumber Total Saham) ──
if _has_listed:
    st.sidebar.success(
        f"📋 **Listed_share.xlsx** tersambung — {_n_listed:,} emiten terdeteksi. "
        "Float Lot Est & % Float Swept 5D akan terisi otomatis."
    )
else:
    # Tidak mungkin terjadi karena data sudah embedded — hanya tampil jika dict kosong
    st.sidebar.info("ℹ️ Data Listed_share menggunakan data **embedded** (959 emiten BEI).")

# ── AUTO-REFRESH SAAT MARKET BUKA ──
import time as _time
_today_date = date.today()
# Auto-refresh hanya aktif jika tanggal analisa = hari ini (bukan backtest)
_enable_autorefresh_ui = st.sidebar.checkbox("🔄 Auto-refresh saat market buka (tiap 5 menit)", value=False)

target_list = sorted(df_emiten['Kode Saham'].unique().tolist())
selected_tickers = st.sidebar.multiselect(
    "Pilih Saham (Kosongkan = Semua):", options=target_list)

min_p       = st.sidebar.number_input("Harga Minimal (Rp)", value=50)
max_p       = st.sidebar.number_input("Harga Maksimal (Rp)", value=25000)
min_vol_lot = st.sidebar.number_input("Min Avg Vol 20D (LOT)", value=100000)
max_ff      = float(st.sidebar.slider("Maximal Free Float (%)", 0.0, 100.0, 100.0))

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Filter Shortlist Utama v34")
min_mfi_change   = st.sidebar.number_input("Min MFI Change 5D", value=8.0, step=0.5)
min_adx          = st.sidebar.number_input("Min ADX (14)", value=22, step=1)
only_outperform  = st.sidebar.checkbox("Hanya Market RS = Outperform", value=True)
show_breakout_only = st.sidebar.checkbox("Hanya 20D Breakout", value=False)

st.sidebar.markdown("**📊 Jalur 1 — Momentum (Shortlist Score)**")
min_shortlist_score = st.sidebar.slider(
    "Min Shortlist Score (Jalur 1)", min_value=6, max_value=17, value=13,
    help=(
        "Jalur masuk momentum biasa berbasis hit-rate empiris.\n"
        "Score ≥13 → ~8 saham, selektif tinggi\n"
        "Score ≥12 → ~25 saham\n"
        "Score ≥10 → ~54 saham (versi lama)\n"
        "Komponen: ADX zone, Dist dari High, MFI, MFI Change, Vol Trend, DI+, OBV, RS, BB Squeeze"
    )
)

st.sidebar.markdown("**🧲 Jalur 2 — Wyckoff Accumulation (WAS)**")
st.sidebar.caption("Saham seperti BSBK: diam-diam diakumulasi bandar sebelum terbang.")
enable_wyckoff_path = st.sidebar.checkbox(
    "Aktifkan Jalur Wyckoff Accumulation", value=True,
    help="Jika aktif, saham dengan akumulasi Wyckoff kuat bisa masuk shortlist meski SS rendah."
)
min_was_score = st.sidebar.slider(
    "Min WAS (Jalur 2)", min_value=5, max_value=10, value=9,
    disabled=not enable_wyckoff_path,
    help="WAS ≥9 = akumulasi bandar sangat kuat. BSBK pre-terbang = WAS 9."
)
min_was_ss_base = st.sidebar.slider(
    "Min SS untuk Jalur Wyckoff", min_value=3, max_value=10, value=6,
    disabled=not enable_wyckoff_path,
    help="SS minimum untuk jalur Wyckoff. Mencegah saham 'random' masuk via jalur ini."
)
min_was_silent = st.sidebar.slider(
    "Min Silent Score (Jalur 2)", min_value=3, max_value=10, value=6,
    disabled=not enable_wyckoff_path,
    help="Silent Score ≥6 = akumulasi tersembunyi terdeteksi jelas."
)
min_was_adx = st.sidebar.slider(
    "Min ADX untuk Jalur Wyckoff", min_value=25, max_value=80, value=50,
    disabled=not enable_wyckoff_path,
    help="ADX ≥50 = Very Strong trend. Bandar sedang aktif bergerak di balik layar."
)

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
    "Min Avg Vol 20D untuk Silent (LOT)", value=1000, step=1000,
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

st.sidebar.markdown("---")
st.sidebar.subheader("⚡ v34: Mode Trading 1 Minggu")
st.sidebar.caption(
    "Filter ketat berbasis backtesting hits vs misses. "
    "Memangkas Silent Accum dari ~47 → ~9 saham dengan hit rate 22% (vs 6% normal)."
)
shortterm_mode = st.sidebar.checkbox(
    "Aktifkan Filter Ketat 1 Minggu", value=False,
    help=(
        "Menambahkan 4 filter ke Silent Accumulation:\n"
        "• MFI (14D) > 65 (hits avg 77 vs misses 61)\n"
        "• MFI Change 5D > 10 (hits avg 19 vs misses 6)\n"
        "• Dist to 20D High > -15% (lebih dekat resistance)\n"
        "• WAS ≥ 6 (akumulasi sudah cukup matang)\n\n"
        "Nonaktifkan untuk mode akumulasi jangka menengah seperti biasa."
    )
)
hide_belum_silent = st.sidebar.checkbox(
    "Sembunyikan Entry Readiness: Belum (Silent Accum)", value=False,
    help=(
        "28 dari 47 saham Silent Accum biasanya masih 'Belum'. "
        "Centang ini untuk hanya tampilkan yang sudah ada minimal 1 trigger (Perhatikan/Tunggu/Siap). "
        "Memotong noise tanpa ubah filter utama."
    )
)

today = date.today()

# ── EFFECTIVE END DATE: pastikan data terakhir yang diambil benar-benar sudah close ──
def get_effective_end_date(selected_date):
    """
    Kembalikan tanggal trading terakhir yang datanya sudah tersedia di yfinance.

    Kasus yang ditangani:
    - Backtest (selected_date < today): pakai selected_date apa adanya
    - Live, jam < 16:10 WIB: mundur ke hari trading sebelumnya karena candle
      hari ini belum close dan belum ada di yfinance
    - Live, jam >= 16:10 WIB: pakai today karena data sudah final
    - Sabtu/Minggu: mundur ke Jumat
    """
    if selected_date < today:
        # Mode backtest — pakai tanggal persis yang dipilih
        return selected_date

    # Mode live — cek apakah data hari ini sudah tersedia
    now_wib = pd.Timestamp.now(tz="Asia/Jakarta")

    # Mundur jika hari ini Sabtu (5) atau Minggu (6) — bursa tutup
    candidate = selected_date
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)

    # Jika hari ini adalah hari bursa tapi belum lewat 16:10 WIB,
    # data hari ini belum close → pakai hari bursa sebelumnya
    market_closed = (now_wib.hour > 16) or (now_wib.hour == 16 and now_wib.minute >= 10)
    if not market_closed:
        candidate -= timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)

    return candidate

_date_range_default = (today - timedelta(days=7), today)
_date_range_input = st.sidebar.date_input(
    "📅 Analisa per tanggal (pilih 2 tanggal = rentang, 1 tanggal = snapshot)",
    value=_date_range_default,
    help=("Pilih 2 tanggal untuk melihat total Volume/Value/Naik-Turun sepanjang "
          "periode tersebut (kolom '...Periode' di tabel hasil). Skor & indikator "
          "(RSI, ADX, MFI, Wyckoff, dll) tetap dihitung per kondisi di tanggal AKHIR "
          "rentang, plus kolom baru 'Perubahan Harga Periode (%)' dari awal ke akhir.")
)

if isinstance(_date_range_input, (list, tuple)):
    if len(_date_range_input) == 2:
        start_d_raw, end_d_raw = _date_range_input
    elif len(_date_range_input) == 1:
        start_d_raw = end_d_raw = _date_range_input[0]
    else:
        start_d_raw = end_d_raw = today
else:
    start_d_raw = end_d_raw = _date_range_input

if start_d_raw > end_d_raw:
    start_d_raw, end_d_raw = end_d_raw, start_d_raw

start_d    = start_d_raw
IS_RANGE_MODE = (start_d_raw != end_d_raw)
end_d      = get_effective_end_date(end_d_raw)

if IS_RANGE_MODE:
    st.sidebar.caption(
        f"📊 Mode rentang aktif: **{start_d.strftime('%d %b %Y')} → {end_d.strftime('%d %b %Y')}** "
        "— lihat kolom '...Periode' di tab Semua Hasil Analisa."
    )

# Tampilkan info tanggal efektif ke user
if end_d != end_d_raw:
    st.sidebar.caption(
        "ℹ️ Data historis 200 hari ke belakang (MA50, BB, ADX). "
        f"Tanggal efektif: {end_d.strftime('%d %b %Y')} "
        f"(candle {end_d_raw.strftime('%d %b %Y')} belum close)"
    )
else:
    st.sidebar.caption(
        "ℹ️ Data historis 200 hari ke belakang (MA50, BB, ADX). "
        f"Data terakhir: {end_d.strftime('%d %b %Y')}"
    )

# ── Backtest mode detection (data cutoff) ──
IS_BACKTEST = (end_d < today)
if IS_BACKTEST:
    st.sidebar.warning(f"⏪ MODE BACKTEST: data s.d. **{end_d.strftime('%d %b %Y')}**")

# ── v35: Tanggal Pembanding untuk Hit Rate (hanya di Mode Backtest + Hit Rate) ──
comparison_date = None
top_gainer_n = 20
hit_method = "Top-N Ranking"
min_gain_pct = None
if IS_BACKTEST_MODE:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Backtest: Tanggal Pembanding")
    st.sidebar.caption(
        "Contoh: tanggal analisa **1 Juli 2026**, tanggal pembanding **5 Juli 2026** "
        "→ dicek apakah saham hasil screener 1 Juli menjadi Top Gainer per 5 Juli."
    )
    _default_compare = end_d_raw + timedelta(days=5)
    comparison_date_raw = st.sidebar.date_input(
        "📅 Tanggal Pembanding (cari Top Gainer)",
        value=_default_compare,
        min_value=end_d_raw + timedelta(days=1),
        help="Harus setelah tanggal analisa (📅 Analisa per tanggal di atas)."
    )
    if comparison_date_raw <= end_d_raw:
        st.sidebar.error("⚠️ Tanggal pembanding harus setelah tanggal analisa.")
    else:
        comparison_date = comparison_date_raw
        st.sidebar.caption(f"✅ Pembanding aktif: **{comparison_date.strftime('%d %b %Y')}**")

    hit_method = st.sidebar.radio(
        "Metode penentuan 'Hit'",
        options=["Top-N Ranking", "Minimum Gain %"],
        index=0,
        help=(
            "Top-N Ranking: saham dianggap Hit jika masuk peringkat top-N gain tertinggi di seluruh universe.\n\n"
            "Minimum Gain %: saham dianggap Hit jika gain-nya (dari tanggal analisa ke tanggal pembanding) "
            "mencapai ambang batas % tertentu, berapapun jumlah saham yang memenuhi."
        )
    )

    if hit_method == "Top-N Ranking":
        top_gainer_n = st.sidebar.number_input(
            "Top-N Gainer dianggap 'Hit'",
            min_value=1, max_value=200, value=20, step=1,
            help=(
                "Saham dengan ranking kenaikan harga (%) top-N di seluruh universe yang di-screen "
                "(dari tanggal analisa ke tanggal pembanding) dianggap 'Top Gainer' / Hit."
            )
        )
        min_gain_pct = None
    else:
        min_gain_pct = st.sidebar.number_input(
            "Minimum Gain (%) dianggap 'Hit'",
            min_value=1.0, max_value=100.0, value=1.0, step=0.5,
            help=(
                "Saham dengan kenaikan harga (%) minimal sebesar ini (dari tanggal analisa ke tanggal "
                "pembanding) dianggap 'Hit' — tidak dibatasi jumlah/ranking."
            )
        )
        top_gainer_n = None

if not IS_BACKTEST:
    # Auto-refresh hanya aktif saat mode live (bukan backtest)
    if _enable_autorefresh_ui:
        now_wib2 = pd.Timestamp.now(tz="Asia/Jakarta")
        is_market_open = (
            now_wib2.weekday() < 5 and
            (9 <= now_wib2.hour < 16) and
            not (now_wib2.hour == 12 and now_wib2.minute < 60 and now_wib2.hour < 13)
        )
        if is_market_open:
            st.sidebar.success("🟢 Market sedang buka — auto-refresh aktif")
            _time.sleep(300)
            st.cache_data.clear()
            st.rerun()
        else:
            st.sidebar.info("🔴 Market tutup — auto-refresh tidak aktif")

# ── SIDEBAR BROKER SUMMARY (v20) ──
st.sidebar.markdown("---")
st.sidebar.subheader("🏦 v20: Broker Summary Analysis")
enable_broker = st.sidebar.checkbox("Aktifkan Broker Summary Analysis", value=False)

broker_mode = st.sidebar.radio(
    "Mode Data Broker",
    ["🌐 Auto Fetch Stockbit", "📁 Upload CSV Manual"],
    help=(
        "Auto Fetch: ambil data broker via Stockbit API (butuh login Stockbit). "
        "Upload CSV: export manual dari RTI/Stockbit lalu upload."
    )
)

if broker_mode == "🌐 Auto Fetch Stockbit":
    st.sidebar.markdown("**🔑 Login Stockbit**")
    sb_username = st.sidebar.text_input(
        "Username / Email Stockbit",
        key="sb_username",
        placeholder="email@gmail.com",
        help="Username atau email akun Stockbit Anda. Tidak disimpan ke server manapun."
    )
    sb_password = st.sidebar.text_input(
        "Password Stockbit",
        type="password",
        key="sb_password",
        help="Password akun Stockbit. Hanya digunakan untuk mengambil Bearer token."
    )
    st.sidebar.caption(
        "🔒 Kredensial hanya dipakai untuk generate Bearer token sesi ini. "
        "Tidak disimpan ke disk maupun server."
    )
    broker_scope = st.sidebar.radio(
        "Saham yang di-fetch:",
        [
            "⭐ Shortlist + Pre-Breakout + Silent (rekomendasi)",
            "🔥 Shortlist + Pre-Breakout saja",
            "🏆 Shortlist saja (tercepat)",
            "📊 Semua hasil analisa (⚠️ lambat)",
        ],
        index=0,
        help="Rekomendasi: 10–50 saham, ~30–60 detik. 'Semua hasil' bisa sangat lambat."
    )
    broker_days = st.sidebar.slider("Periode Broker Summary (hari)", 5, 180, 30)
    st.sidebar.caption(
        "⏱️ Estimasi: ~1 detik/saham. "
        "30 saham ≈ 30 detik. Pilih scope sesempit mungkin."
    )
else:
    sb_username  = ""
    sb_password  = ""
    broker_scope = "📁 Upload CSV Manual"
    broker_days  = 30

min_broker_score = st.sidebar.slider(
    "Min Broker Score untuk Moonstock", 0, 10, 6,
    help="≥6 = Akumulasi. ≥8 = Akumulasi Kuat. Dipakai untuk filter tab Moonstock Radar."
)
st.sidebar.caption(
    "Broker Score 0–10: smart money net buy, rasio asing, pola distribusi. "
    "Score ≥6 = akumulasi institusi terdeteksi."
)

st.sidebar.markdown("---")
btn_analisa = st.sidebar.button("🚀 JALANKAN ANALISA", use_container_width=True, type="primary")
if st.sidebar.button("🗑️ Clear Cache + Logout Stockbit", use_container_width=True):
    st.cache_data.clear()
    st.session_state.pop("sb_token", None)
    st.sidebar.success("Cache & token Stockbit dibersihkan! Silakan login ulang dan klik JALANKAN ANALISA.")

# ─────────────────────────────────────────────
# 8. FORMAT & STYLE
# ─────────────────────────────────────────────
FORMAT_DICT = {
    'Rel Vol (20D)':         "{:.2f}x",
    'Rel Vol (50D)':         "{:.2f}x",
    'Value (Rp)':            lambda x: f"{x/1e9:.2f} B",
    'Free Float (%)':        "{:.2f}%",
    'MFI (14D)':             "{:.2f}",
    'MFI Change 5D':         "{:+.2f}",
    'RSI (14)':              "{:.2f}",
    'ADX (14)':              "{:.2f}",
    'Dist to 20D High (%)':  "{:.2f}%",
}

def compute_gain_vs_universe(universe_tickers_jk, base_date, compare_date):
    """
    v35 — Hitung kenaikan harga (%) dari base_date ke compare_date untuk seluruh
    universe saham yang di-screen, lalu ranking dari gain tertinggi ke terendah.
    Dipakai untuk menentukan siapa saja "Top Gainer" pada compare_date, sebagai
    basis perhitungan hit rate backtest.

    Returns: DataFrame dengan kolom
      Kode Saham, Harga Base, Harga Pembanding, Gain (%), Rank
    (Rank 1 = gain tertinggi). DataFrame kosong jika data tidak tersedia.
    """
    df_c2, _, _, _, _ = fetch_yf_all_data(tuple(universe_tickers_jk), compare_date)
    if df_c2.empty:
        return pd.DataFrame()

    base_ts    = pd.Timestamp(base_date)
    compare_ts = pd.Timestamp(compare_date)

    rows = []
    for t_jk in universe_tickers_jk:
        if t_jk not in df_c2.columns:
            continue
        series = df_c2[t_jk].dropna()
        series_base = series[series.index <= base_ts]
        series_cmp  = series[series.index <= compare_ts]
        if series_base.empty or series_cmp.empty:
            continue
        price_base = float(series_base.iloc[-1])
        price_cmp  = float(series_cmp.iloc[-1])
        if price_base <= 0:
            continue
        gain_pct = (price_cmp / price_base - 1) * 100
        rows.append({
            "Kode Saham":        t_jk.replace(".JK", ""),
            "Harga Base":        price_base,
            "Harga Pembanding":  price_cmp,
            "Gain (%)":          round(gain_pct, 2),
        })

    gain_df = pd.DataFrame(rows)
    if gain_df.empty:
        return gain_df

    gain_df = gain_df.sort_values("Gain (%)", ascending=False).reset_index(drop=True)
    gain_df["Rank"] = gain_df.index + 1
    return gain_df


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
    _map(style_value,          'Value (Rp)')
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
    _map(style_wyckoff_score,  'Wyckoff Score')
    _map(style_wyckoff_phase,  'Wyckoff Phase')
    _map(style_was,            'WAS')
    _map(style_jalur_masuk,    'Jalur Masuk')
    # ── v29: Float Analysis styling ──
    _map(style_float_urgency,  'Float Urgency')
    _map(style_vol_accel,      'Vol Accel (5D/20D)')
    _map(style_accumulated_lot, 'Estimasi Lot Terkumpul')
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

        # ── v35 DEBUG: ticker yang bahkan tidak muncul sama sekali di hasil
        # download yfinance (bukan sekadar gagal filter di dalam loop) ──
        _fetched_codes = set(str(c).replace(".JK", "").upper() for c in df_c.columns) if not df_c.empty else set()
        _missing_from_fetch = [
            {"Kode": code, "Alasan": "Tidak ada kolom sama sekali di hasil yf.download "
                                      "(gagal fetch / delisted / rate-limited)"}
            for code in active_list if code.upper() not in _fetched_codes
        ]

        if not df_c.empty:
            df_res, shortlist, prebreakout_list, silent_list, skip_log, gemini_list = get_signals_and_data(
                df_c, df_v, df_h, df_l, df_o, df_emiten, min_vol_lot,
                min_mfi_change_watch=min_mfi_change_watch,
                min_early_score=min_early_score,
                watch_require_outperform=watch_require_outperform,
                min_vol_silent_lot=min_vol_silent_lot,
                min_silent_score=min_silent_score,
                min_shortlist_score=min_shortlist_score,
                enable_was_filter=False,
                min_was_score=min_was_score,
                enable_wyckoff_path=enable_wyckoff_path,
                min_was_ss_base=min_was_ss_base,
                min_was_silent=min_was_silent,
                min_was_adx=min_was_adx,
                shortterm_mode=shortterm_mode,
                start_date=start_d if IS_RANGE_MODE else None,
            )

            # ── v35 DEBUG: gabungkan semua saham yang gugur + alasannya, simpan
            # untuk ditampilkan di panel diagnostik bawah sidebar ──
            st.session_state["v35_skip_log"] = _missing_from_fetch + skip_log

            # ── BROKER SUMMARY SCORING (v20) via Stockbit ──
            broker_scores = {}
            if enable_broker:
                if broker_mode == "🌐 Auto Fetch Stockbit":
                    # ── Validasi kredensial ──
                    if not sb_username or not sb_password:
                        st.warning(
                            "⚠️ Masukkan **Username** dan **Password Stockbit** di sidebar "
                            "sebelum menjalankan analisa dengan Broker Summary aktif."
                        )
                    else:
                        # ── Login Stockbit (cache token di session_state) ──
                        token = st.session_state.get("sb_token")
                        if not token:
                            with st.spinner("🔑 Login ke Stockbit..."):
                                token = _sb_get_token(sb_username, sb_password)
                            if token:
                                st.session_state["sb_token"] = token
                                st.success("✅ Login Stockbit berhasil! Token tersimpan untuk sesi ini.")
                            else:
                                st.error(
                                    "❌ Login Stockbit gagal. Periksa username/password di sidebar. "
                                    "Pastikan akun Stockbit Anda aktif."
                                )

                        if token:
                            # ── Tentukan scope saham ──
                            if "Semua hasil analisa" in broker_scope:
                                tickers_for_broker = df_res['Kode Saham'].tolist()
                            elif "Shortlist + Pre-Breakout + Silent" in broker_scope:
                                tickers_for_broker = list(dict.fromkeys(
                                    shortlist + prebreakout_list + silent_list
                                ))
                            elif "Shortlist + Pre-Breakout" in broker_scope:
                                tickers_for_broker = list(dict.fromkeys(
                                    shortlist + prebreakout_list
                                ))
                            else:
                                tickers_for_broker = list(shortlist)

                            n_fetch = len(tickers_for_broker)
                            est_sec = n_fetch * 1.0

                            if n_fetch == 0:
                                st.info(
                                    "ℹ️ Tidak ada saham dalam scope yang dipilih. "
                                    "Coba perluas scope atau jalankan analisa dulu."
                                )
                            else:
                                if n_fetch > 50:
                                    st.warning(
                                        f"⚠️ **{n_fetch} saham** akan di-fetch "
                                        f"(estimasi ~{est_sec/60:.1f} menit). "
                                        "Pertimbangkan scope lebih sempit di sidebar."
                                    )
                                scope_label = broker_scope.split("(")[0].strip()
                                prog = st.progress(
                                    0,
                                    text=f"📊 Stockbit broker fetch [{scope_label}] — {n_fetch} saham, est. {est_sec:.0f} detik..."
                                )
                                def _broker_progress(frac, msg):
                                    prog.progress(min(frac, 1.0), text=msg)

                                broker_scores = fetch_broker_scores_batch(
                                    tickers_for_broker,
                                    token=token,
                                    days=broker_days,
                                    delay=1.0,
                                    progress_callback=_broker_progress,
                                )
                                prog.empty()

                                # Cek apakah semua No Data (indikasi token expired)
                                no_data_count = sum(
                                    1 for v in broker_scores.values()
                                    if v.get("signal") == "No Data"
                                )
                                if no_data_count == n_fetch and n_fetch > 0:
                                    st.error(
                                        "❌ Semua saham gagal di-fetch — kemungkinan token Stockbit expired. "
                                        "Klik **Clear Cache** di sidebar lalu jalankan ulang untuk login ulang."
                                    )
                                    st.session_state.pop("sb_token", None)
                                else:
                                    ok_count = n_fetch - no_data_count
                                    st.success(
                                        f"✅ Stockbit broker data: **{ok_count}/{n_fetch} saham** berhasil "
                                        f"(scope: {scope_label})"
                                    )
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

            # ── COIL WATCH: Pola "Pegas Terkompresi" ──
            if not df_res.empty:
                coil_mask = (
                    (df_res['Silent Score'] >= 7) &
                    (df_res['Composite Rank'] >= 8) &
                    (df_res['ADX (14)'] > 50) &
                    (df_res['ADX Direction'].str.contains('Bullish', na=False)) &
                    (df_res['OBV Trend'].str.contains('Rising', na=False)) &
                    (df_res['Price Tightness (%)'] < 3.0) &
                    (df_res['Dist to 20D High (%)'].between(-8, 0))
                )
                df_coil_raw = df_res[coil_mask].copy()
                df_coil_raw['Entry Readiness Score'] = df_coil_raw.apply(calc_entry_readiness, axis=1)
                df_coil_raw['Entry Readiness'] = df_coil_raw['Entry Readiness Score'].apply(entry_readiness_label)
                df_coil_raw = df_coil_raw.sort_values(['Entry Readiness Score', 'Composite Rank'], ascending=[False, False])
                coil_list = df_coil_raw['Kode Saham'].tolist()
            else:
                df_coil_raw = pd.DataFrame()
                coil_list = []

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

            # ── v35: BACKTEST HIT RATE vs TOP GAINER ──
            gain_df          = pd.DataFrame()
            hitrate_summary  = pd.DataFrame()
            if IS_BACKTEST_MODE and comparison_date is not None and not df_res.empty:
                with st.spinner(
                    f"🎯 Menghitung Top Gainer per {comparison_date.strftime('%d %b %Y')} "
                    f"untuk {len(tickers_jk)} saham universe..."
                ):
                    gain_df = compute_gain_vs_universe(tickers_jk, end_d, comparison_date)

                if gain_df.empty:
                    st.warning(
                        "⚠️ Data harga pada tanggal pembanding tidak tersedia "
                        "(kemungkinan hari libur bursa atau data belum ter-update di yfinance)."
                    )
                else:
                    n_universe = len(gain_df)
                    if hit_method == "Minimum Gain %":
                        gain_df["Top Gainer"] = gain_df["Gain (%)"] >= float(min_gain_pct)
                        n_top = int(gain_df["Top Gainer"].sum())
                    else:
                        n_top = max(1, min(int(top_gainer_n), n_universe))
                        gain_df["Top Gainer"] = gain_df["Rank"] <= n_top

                    candidate_lists = {
                        "Shortlist":                 shortlist,
                        "Pre-Breakout Watch":        prebreakout_list,
                        "Silent Accumulation":       silent_list,
                        "Coil Watch":                coil_list,
                    }
                    if moonstock_list:
                        candidate_lists["Moonstock (Broker Score)"] = moonstock_list

                    rows_summary = []
                    for _name, _codes in candidate_lists.items():
                        _codes = list(dict.fromkeys(_codes))
                        _sub   = gain_df[gain_df["Kode Saham"].isin(_codes)]
                        _n_total = len(_codes)
                        _n_hit   = int(_sub["Top Gainer"].sum()) if _n_total else 0
                        _hit_rate = round(_n_hit / _n_total * 100, 1) if _n_total else 0.0
                        rows_summary.append({
                            "List":               _name,
                            "Jumlah Saham":        _n_total,
                            "Jumlah Top Gainer":   _n_hit,
                            "Hit Rate (%)":        _hit_rate,
                        })

                    # Baseline acak: ekspektasi hit rate jika memilih saham secara random dari universe
                    baseline_rate = round(n_top / n_universe * 100, 1) if n_universe else 0.0
                    rows_summary.append({
                        "List":               "🎲 Baseline Acak (seluruh universe)",
                        "Jumlah Saham":        n_universe,
                        "Jumlah Top Gainer":   n_top,
                        "Hit Rate (%)":        baseline_rate,
                    })
                    hitrate_summary = pd.DataFrame(rows_summary)

            # ── Simpan semua hasil ke session_state ──
            st.session_state.analisa_hasil = {
                "df_res":           df_res,
                "shortlist":        shortlist,
                "prebreakout_list": prebreakout_list,
                "silent_list":      silent_list,
                "gemini_list":      gemini_list,   # ── v37 ──
                "df_res_filtered":  df_res_filtered,
                "broker_scores":    broker_scores,
                "moonstock_list":   moonstock_list,
                "coil_list":        coil_list,
                "end_d":            end_d,  # simpan untuk banner & chart backtest
                "comparison_date":  comparison_date,     # v35
                "top_gainer_n":     top_gainer_n,         # v35
                "hit_method":       hit_method,           # v35b
                "min_gain_pct":     min_gain_pct,          # v35b
                "gain_df":          gain_df,              # v35
                "hitrate_summary":  hitrate_summary,      # v35
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
    gemini_list      = _h.get("gemini_list", [])   # ── v37 ──
    df_res_filtered  = _h["df_res_filtered"]
    broker_scores    = _h.get("broker_scores", {})
    moonstock_list   = _h.get("moonstock_list", [])
    coil_list        = _h.get("coil_list", [])
    # Ambil end_date dari session_state agar banner & chart konsisten meski sidebar berubah
    _end_d_render    = _h.get("end_d", end_d)

    # ── Tambahkan Entry Readiness ke df_res untuk Semua Analisa ──
    if not df_res.empty:
        df_res['Entry Readiness Score'] = df_res.apply(calc_entry_readiness, axis=1)
        df_res['Entry Readiness'] = df_res['Entry Readiness Score'].apply(entry_readiness_label)

    # ── BACKTEST MODE BANNER ──
    if _end_d_render < date.today():
        st.warning(
            f"⏪ **MODE BACKTEST** — Seluruh analisa (indikator, chart, Live Signal) "
            f"dihitung dari data historis s.d. **{_end_d_render.strftime('%d %B %Y')}**. "
            f"Data setelah tanggal ini tidak digunakan sama sekali."
        )

    # ── v35: HASIL HIT RATE BACKTEST vs TOP GAINER ──
    _comparison_date = _h.get("comparison_date")
    _gain_df         = _h.get("gain_df", pd.DataFrame())
    _hitrate_summary = _h.get("hitrate_summary", pd.DataFrame())
    _top_gainer_n    = _h.get("top_gainer_n", 20)
    _hit_method      = _h.get("hit_method", "Top-N Ranking")
    _min_gain_pct    = _h.get("min_gain_pct")

    if IS_BACKTEST_MODE and _comparison_date is not None:
        st.markdown("## 🎯 Hasil Backtest: Hit Rate vs Top Gainer")
        if _hit_method == "Minimum Gain %":
            _hit_desc = f"Saham dengan kenaikan harga **≥ {_min_gain_pct}%** dianggap **'Hit'**."
        else:
            _hit_desc = (
                f"Saham dengan ranking kenaikan harga **Top {_top_gainer_n}** dari seluruh universe "
                f"dianggap **'Top Gainer' / Hit'**."
            )
        st.info(
            f"Screener dijalankan per **{_end_d_render.strftime('%d %b %Y')}**, "
            f"dibandingkan dengan pergerakan harga per **{_comparison_date.strftime('%d %b %Y')}**. "
            f"{_hit_desc}"
        )

        if _hitrate_summary.empty:
            st.warning(
                "Belum ada data hit rate untuk kombinasi tanggal ini. "
                "Coba jalankan ulang analisa, atau pastikan tanggal pembanding adalah hari bursa."
            )
        else:
            st.dataframe(
                _hitrate_summary,
                use_container_width=True, hide_index=True,
                column_config={
                    "Hit Rate (%)": st.column_config.ProgressColumn(
                        "Hit Rate (%)", min_value=0, max_value=100, format="%.1f%%"
                    ),
                },
            )
            st.caption(
                "💡 Bandingkan **Hit Rate** tiap list dengan **Baseline Acak** — semakin jauh di atas "
                "baseline, semakin bagus kemampuan filter screener dalam menangkap saham yang benar-benar naik."
            )

            with st.expander(f"📋 Detail Gain Seluruh Universe ({len(_gain_df)} saham) — di-rank dari gain tertinggi"):
                _base_date_str  = _end_d_render.strftime("%d/%m/%Y")
                _comp_date_str  = _comparison_date.strftime("%d/%m/%Y")
                _col_base = f"Harga Base ({_base_date_str})"
                _col_comp = f"Harga Pembanding ({_comp_date_str})"

                _gain_show = _gain_df.sort_values("Rank")[
                    ["Rank", "Kode Saham", "Harga Base", "Harga Pembanding", "Gain (%)", "Top Gainer"]
                ].copy()
                _gain_show = _gain_show.rename(columns={
                    "Harga Base":       _col_base,
                    "Harga Pembanding": _col_comp,
                })
                _gain_show["Ada di Shortlist"]  = _gain_show["Kode Saham"].isin(shortlist)
                _gain_show["Ada di Pre-Breakout"] = _gain_show["Kode Saham"].isin(prebreakout_list)
                _gain_show["Ada di Silent Accum"] = _gain_show["Kode Saham"].isin(silent_list)
                st.dataframe(_gain_show, use_container_width=True, hide_index=True)

                _xlsx_buf = BytesIO()
                with pd.ExcelWriter(_xlsx_buf, engine="xlsxwriter") as _writer:
                    _gain_show.to_excel(_writer, index=False, sheet_name="Detail Gain")
                st.download_button(
                    "⬇️ Download Detail Gain (Excel)", data=_xlsx_buf.getvalue(),
                    file_name=f"backtest_hitrate_{_end_d_render}_{_comparison_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        st.markdown("---")

    # ── Upload CSV broker (mode manual, di luar tombol analisa) ──
    if enable_broker and "Upload CSV" in broker_mode:
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
            'Dist to 20D High (%)', 'Last Price', 'Value (Rp)', 'Rel Vol (20D)', 'Rel Vol (50D)',
            'Consec Up Days', 'AvgVol20 (Lot)',
        ]
        # ── v35: Kolom agregat rentang tanggal — hanya relevan kalau mode rentang aktif ──
        period_col = (
            ['Volume Periode (Lot)', 'Value Periode (Rp)', 'Hari Naik (Periode)',
             'Hari Turun (Periode)', 'Perubahan Harga Periode (%)']
            if IS_RANGE_MODE else []
        )
        score_col      = ['Early Momentum Score'] if show_score_in_table else []
        comp_rank_col  = ['Composite Rank', 'Composite Criteria'] if show_composite_rank else []
        watch_col      = ['Pre-Breakout Watch']
        silent_col     = ['Silent Score', 'BB Squeeze', 'OBV Trend', 'Vol Trend Ratio', 'Silent Accum']
        broker_col     = ['Broker Score', 'Broker Signal', 'Smart Net Lot', 'Asing Net Lot'] if (enable_broker and broker_scores) else []
        reason_col     = ['Shortlist Reasons', 'Chart Analysis', 'Visual Chart Analysis']
        # ── v29: Float Analysis columns ──
        float_col      = ['Vol Accel (5D/20D)', 'Float Urgency', 'Estimasi Lot Terkumpul',
                          '% Float Swept 5D', 'Float Lot Est', 'Float Note']

        all_display_cols = base_cols + period_col + score_col + comp_rank_col + watch_col + silent_col + broker_col + reason_col + float_col

        # Sort default: Composite Rank DESC, lalu Early Momentum Score DESC
        sort_cols = []
        if show_composite_rank and 'Composite Rank' in df_res.columns:
            sort_cols.append('Composite Rank')
        if show_score_in_table and 'Early Momentum Score' in df_res.columns:
            sort_cols.append('Early Momentum Score')
        if sort_cols:
            df_res_filtered = df_res_filtered.sort_values(sort_cols, ascending=False)

        # ── v35 DEBUG: Panel diagnostik — kenapa saham tertentu gugur dari scan ──
        _skip_log = st.session_state.get("v35_skip_log", [])
        if _skip_log:
            with st.expander(f"🩺 Diagnostik: {len(_skip_log)} saham di universe scan tidak muncul di hasil (klik untuk lihat alasan)"):
                _df_skip = pd.DataFrame(_skip_log).drop_duplicates(subset="Kode").sort_values("Kode")
                _search_skip = st.text_input("Cari kode saham (mis. TIFA, AGAR)", value="", key="v35_skip_search")
                if _search_skip.strip():
                    _df_skip = _df_skip[_df_skip["Kode"].str.contains(_search_skip.strip().upper())]
                st.dataframe(_df_skip, use_container_width=True, hide_index=True)

        # ── TAB LAYOUT ──
        has_broker_data = enable_broker and bool(broker_scores)
        tab_labels = [
            "🔥 Shortlist Utama",
            "🎯 Shortlist Gemini",
            "🔭 Pre-Breakout Watch (Opsi A)",
            "🕵️ Silent Accumulation (v18)",
            "🌀 Coil Watch (v23)",
            "💥 Pre-Explosion Watch",
            "🏛️ Wyckoff Phases (v26)",
            "🧮 Float Analysis (v34)",
            "🔍 Semua Hasil Analisa",
        ]
        if has_broker_data:
            tab_labels.append("🌙 Moonstock Radar (v20)")

        tabs = st.tabs(tab_labels)
        tab1            = tabs[0]
        tab_gemini      = tabs[1]
        tab2            = tabs[2]
        tab3            = tabs[3]
        tab_coil        = tabs[4]
        tab_explosion   = tabs[5]
        tab_wyckoff     = tabs[6]
        tab_float       = tabs[7]
        tab4            = tabs[8]
        tab5            = tabs[9] if has_broker_data else None

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
                        show_plotly_candlestick(selected_tv_s, chart_key=f"plotly_tab1_{selected_tv_s}", end_date=_end_d_render)
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
            # SUB-SECTION: SHAKEOUT SHORTLIST
            # (Wyckoff Phase C-Shakeout + Above MA20 YA + Shakeout Verdict VALID)
            # ═══════════════════════════════════════
            st.divider()
            st.markdown("### 🎯 Shakeout Shortlist — Phase C Shakeout + Above MA20 + Verdict VALID")
            st.markdown("""
> **Filosofi:** Jalur shortlist terpisah yang menangkap saham yang baru mengalami
> **shakeout (Wyckoff Phase C)**, sudah kembali **di atas MA20**, dan shakeout-nya
> **dikonfirmasi VALID** oleh Shakeout Verdict (bukan bull trap / jebakan).
>
> ⚠️ **Kenapa Verdict wajib:** Wyckoff Phase = Shakeout + Above MA20 saja **tidak cukup** —
> secara historis ~45% saham yang lolos dua filter itu ternyata **🔴 JEBAKAN**.
> Shakeout Confidence memisahkan dengan jelas: saham **VALID** rata-rata confidence ~84
> (rentang 70-100), saham **JEBAKAN** rata-rata hanya ~10 (rentang 0-43).
""")

            min_shakeout_conf = st.slider(
                "Min Shakeout Confidence", min_value=0, max_value=100, value=70, step=5,
                help="Confidence dari Shakeout Verdict. ≥70 = rentang khas saham VALID; "
                     "saham JEBAKAN biasanya di bawah 45.",
                key="min_shakeout_conf_tab1"
            )

            _shk_required_cols = ['Wyckoff Phase', 'Above MA20', 'Shakeout Verdict', 'Shakeout Confidence']
            if not df_res.empty and all(c in df_res.columns for c in _shk_required_cols):
                df_shk = df_res.copy()
                if 'Last Price' in df_shk.columns:
                    df_shk = df_shk[(df_shk['Last Price'] >= min_p) & (df_shk['Last Price'] <= max_p)]
                if 'Free Float (%)' in df_shk.columns:
                    df_shk = df_shk[df_shk['Free Float (%)'] <= max_ff]

                df_shk = df_shk[
                    df_shk['Wyckoff Phase'].astype(str).str.startswith('Phase C — Shakeout') &
                    (df_shk['Above MA20'] == 'YA') &
                    df_shk['Shakeout Verdict'].astype(str).str.contains('VALID') &
                    (df_shk['Shakeout Confidence'] >= min_shakeout_conf)
                ].sort_values(['Shakeout Confidence', 'Wyckoff Score'], ascending=False)

                if not df_shk.empty:
                    shk_display_cols = [c for c in [
                        'Kode Saham', 'Last Price', 'Value (Rp)',
                        'Wyckoff Phase', 'Wyckoff Score',
                        'Shakeout Type', 'Shakeout Confidence', 'Shakeout Verdict',
                        'Shakeout Days Ago', 'Entry Readiness', 'Above MA20',
                        'Free Float (%)', 'Wyckoff Reasons',
                    ] if c in df_shk.columns]

                    st.dataframe(
                        df_shk[shk_display_cols].style.format({
                            'Free Float (%)':       '{:.1f}%',
                            'Shakeout Confidence':  '{:.0f}%',
                        }, na_rep="-"),
                        use_container_width=True
                    )
                    st.caption(
                        f"Menampilkan {len(df_shk)} saham — Phase C Shakeout + Above MA20 YA + "
                        f"Verdict VALID + Confidence ≥ {min_shakeout_conf}%"
                    )

                    # ── TradingView Widget ──
                    st.markdown("#### 📈 TradingView Chart")
                    ticker_list_shk = df_shk['Kode Saham'].tolist()
                    default_idx_shk = ticker_list_shk.index(st.session_state.tv_ticker) \
                        if st.session_state.tv_ticker in ticker_list_shk else 0
                    selected_tv_shk = st.selectbox(
                        "🔍 Pilih saham untuk chart:", ticker_list_shk,
                        index=default_idx_shk, key="tv_select_tab1_shakeout"
                    )
                    if selected_tv_shk:
                        st.session_state.tv_ticker = selected_tv_shk
                        chart_mode_shk = st.radio(
                            "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                            key="chart_mode_tab1_shakeout", horizontal=True
                        )
                        if "Plotly" in chart_mode_shk:
                            show_plotly_candlestick(selected_tv_shk, chart_key=f"plotly_tab1_shk_{selected_tv_shk}", end_date=_end_d_render)
                        else:
                            show_tradingview_widget(selected_tv_shk)

                    st.markdown("#### 📋 Ringkasan Kandidat Shakeout Shortlist")
                    for _, row in df_shk.iterrows():
                        conf = int(row.get('Shakeout Confidence', 0))
                        entry_r = row.get('Entry Readiness', '-')
                        st.markdown(
                            f"**{row['Kode Saham']}** | Rp {row['Last Price']:,} | "
                            f"{row.get('Wyckoff Phase','')} | "
                            f"Confidence: **{conf}%** | {row.get('Shakeout Verdict','')} | "
                            f"Entry Readiness: {entry_r}"
                        )
                        bar_color = "#2ecc71" if conf >= 70 else "#f39c12" if conf >= 45 else "#e74c3c"
                        st.markdown(
                            f"<div style='background:#333;border-radius:4px;height:8px;margin:2px 0 10px 0'>"
                            f"<div style='background:{bar_color};width:{conf}%;height:8px;border-radius:4px'></div>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                else:
                    st.info(
                        f"Tidak ada saham yang memenuhi Phase C Shakeout + Above MA20 YA + "
                        f"Verdict VALID + Confidence ≥ {min_shakeout_conf}% hari ini. "
                        f"Coba turunkan slider Min Shakeout Confidence."
                    )
            else:
                st.warning("Kolom Wyckoff Phase / Above MA20 / Shakeout Verdict / Shakeout Confidence belum tersedia di data hasil analisa.")

        # ═══════════════════════════════════════
        # TAB GEMINI: SHORTLIST GEMINI (v37) — replika rule screener Gemini
        # ═══════════════════════════════════════
        with tab_gemini:
            st.subheader("🎯 Shortlist Gemini — Replika Rule Screener Gemini 2P & 7P")
            st.caption(
                "Filter di tab ini APA ADANYA meniru rule di screener Gemini kamu "
                "(Price vs MA20/MA50, Volume spike/MA5/MA20, Free Float < 40%). "
                "**Bukan skoring bertingkat** seperti Shortlist Utama — jadi saham yang "
                "masih di fase awal breakout tetap masuk meski ADX/skor Wyckoff belum tinggi. "
                "Kolom skor app_v36 (Wyckoff, Composite, Shortlist Score, dst) tetap ditampilkan "
                "di sini sebagai **info tambahan saja** untuk riset lanjutan — bukan sebagai penyaring."
            )

            df_g = (df_res_filtered[df_res_filtered['Kode Saham'].isin(gemini_list)]
                    if not df_res_filtered.empty else pd.DataFrame())

            if not df_g.empty:
                gemini_info_cols = [
                    'Gemini Rule Match', 'Price MA5', 'Price MA20', 'Price MA50',
                    'Volume MA5 (Lot)', 'Volume MA20 (Lot)',
                ]
                gemini_context_cols = [
                    'Wyckoff Score', 'Wyckoff Phase', 'WAS', 'Shortlist Score',
                    'Composite Rank', 'ADX (14)', 'ADX Direction',
                ]
                cols_g = [c for c in (base_cols + gemini_info_cols + gemini_context_cols)
                          if c in df_g.columns]
                # Urutkan berdasarkan Wyckoff Score / Shortlist Score sebagai referensi kualitas
                # (bukan filter — semua tetap tampil, hanya urutan tampilan)
                _sort_g = [c for c in ['Wyckoff Score', 'Shortlist Score'] if c in df_g.columns]
                if _sort_g:
                    df_g = df_g.sort_values(_sort_g, ascending=False)

                st.dataframe(
                    apply_full_style(df_g[cols_g].style, include_score=False),
                    use_container_width=True
                )

                n_overlap = df_g['Kode Saham'].isin(shortlist).sum()
                st.caption(
                    f"📊 {len(df_g)} saham lolos Shortlist Gemini. "
                    f"{n_overlap} di antaranya juga masuk Shortlist Utama app_v36 "
                    f"(overlap dua sistem); sisanya kandidat yang HANYA ditangkap rule Gemini "
                    f"— biasanya saham di fase paling awal yang belum lolos hard filter ADX Bullish "
                    f"atau threshold skor Shortlist Utama."
                )

                st.markdown("#### 📈 TradingView Chart")
                st.caption("Pilih nama saham dari dropdown untuk melihat chart TradingView langsung di sini.")
                ticker_list_g = df_g['Kode Saham'].tolist()
                default_idx_g = ticker_list_g.index(st.session_state.tv_ticker) \
                    if st.session_state.tv_ticker in ticker_list_g else 0
                selected_tv_g = st.selectbox(
                    "🔍 Pilih saham untuk chart:", ticker_list_g,
                    index=default_idx_g, key="tv_select_tab_gemini"
                )
                if selected_tv_g:
                    st.session_state.tv_ticker = selected_tv_g
                    chart_mode_g = st.radio(
                        "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                        key="chart_mode_tab_gemini", horizontal=True
                    )
                    if "Plotly" in chart_mode_g:
                        show_plotly_candlestick(selected_tv_g, chart_key=f"plotly_tab_gemini_{selected_tv_g}", end_date=_end_d_render)
                    else:
                        show_tradingview_widget(selected_tv_g)
            else:
                st.info(
                    "Tidak ada saham yang lolos rule Gemini (2P atau 7P) untuk tanggal/universe ini. "
                    "Coba perluas universe saham yang di-scan atau cek tanggal analisa."
                )

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
                            show_plotly_candlestick(selected_tv_w, chart_key=f"plotly_tab2_{selected_tv_w}", end_date=_end_d_render)
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
                    # Hitung Entry Readiness di sini agar filter bisa dipakai
                    df_silent_raw['Entry Readiness Score'] = df_silent_raw.apply(calc_entry_readiness, axis=1)
                    df_silent_raw['Entry Readiness'] = df_silent_raw['Entry Readiness Score'].apply(entry_readiness_label)
                    silent_mask = (
                        (df_silent_raw['Last Price'] >= min_p) &
                        (df_silent_raw['Last Price'] <= max_p) &
                        (df_silent_raw['Free Float (%)'] <= max_ff)
                    )
                    if silent_require_squeeze:
                        silent_mask &= df_silent_raw['BB Squeeze'].isin(['SQUEEZE 🔥', 'Sempit'])
                    # v32: sembunyikan Entry Readiness Belum
                    if hide_belum_silent:
                        silent_mask &= df_silent_raw['Entry Readiness Score'] >= 1
                    df_silent = df_silent_raw[silent_mask].copy()
                    df_silent = df_silent.sort_values(['Entry Readiness Score', 'Silent Score'], ascending=[False, False])
                else:
                    df_silent = pd.DataFrame()

                if not df_silent.empty:
                    # v32 badge
                    if shortterm_mode:
                        st.success("⚡ Mode 1 Minggu AKTIF — Filter ketat: MFI>65, MFI Change>10, Dist>-15%, WAS≥6")
                    # Kolom khusus silent accumulation
                    silent_cols = [
                        'Kode Saham', 'Last Price', 'Value (Rp)', 'Free Float (%)', 'AvgVol20 (Lot)',
                        'Entry Readiness', 'Entry Readiness Score',
                        'Vol Spike Today (x ADV20)', 'Gap to R1 (%)',
                        'Composite Rank', 'Silent Score', 'BB Squeeze', 'BB Width (%)', 'OBV Trend',
                        'Vol Trend Ratio', 'Price Tightness (%)',
                        'MFI (14D)', 'MFI Change 5D', 'RSI (14)',
                        'ADX (14)', 'ADX Direction', 'ADX Trend',
                        'Above MA20', 'Dist to 20D High (%)', 'Rel Vol (20D)',
                        'WAS', 'Wyckoff Phase',
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
                                'Free Float (%)':           '{:.1f}%',
                                'MFI (14D)':                '{:.1f}',
                                'MFI Change 5D':            '{:+.1f}',
                                'RSI (14)':                 '{:.1f}',
                                'ADX (14)':                 '{:.1f}',
                                'BB Width (%)':             '{:.2f}%',
                                'Vol Trend Ratio':          '{:.2f}x',
                                'Price Tightness (%)':      '{:.2f}%',
                                'Dist to 20D High (%)':     '{:.2f}%',
                                'Rel Vol (20D)':            '{:.2f}x',
                                'Vol Spike Today (x ADV20)':'{:.2f}x',
                                'Gap to R1 (%)':            '{:+.2f}%',
                            }, na_rep="-")
                        )
                        if 'Composite Rank' in df_styled.data.columns and show_composite_rank:
                            styled = styled.map(style_composite_rank, subset=['Composite Rank'])
                        if 'Entry Readiness Score' in df_styled.data.columns:
                            styled = styled.map(style_entry_readiness, subset=['Entry Readiness Score'])
                        if 'WAS' in df_styled.data.columns:
                            styled = styled.map(style_was, subset=['WAS'])
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
                            show_plotly_candlestick(selected_tv_si, chart_key=f"plotly_tab3_{selected_tv_si}", end_date=_end_d_render)
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
        # TAB COIL WATCH (v23)
        # ═══════════════════════════════════════
        with tab_coil:
            st.subheader("🌀 Coil Watch — Pegas Terkompresi (v23)")
            st.markdown("""
> **Filosofi:** Menangkap saham seperti **BSBK** — ADX sangat kuat, harga sideways sangat ketat,
> OBV naik diam-diam, tapi belum breakout. Kombinasi ini adalah **"energi terkompresi"** yang
> sewaktu-waktu bisa meledak. Tab ini memfilter kandidat terbaik dari Silent Accumulation
> dan menambahkan **Entry Readiness** untuk membantu timing entry.
>
> 🎯 **Cara pakai:** Pantau saham dengan Entry Readiness 🟢 setiap hari. Entry saat salah satu
> trigger muncul: Volume Spike (>2x), MFI Lonjak (>15 dalam 5 hari), atau Breakout resistance.
""")

            # Rebuild df_coil dari df_res (fresh, pakai data yang sudah ada di session_state)
            if not df_res.empty:
                coil_mask = (
                    (df_res['Silent Score'] >= 7) &
                    (df_res['Composite Rank'] >= 8) &
                    (df_res['ADX (14)'] > 50) &
                    (df_res['ADX Direction'].str.contains('Bullish', na=False)) &
                    (df_res['OBV Trend'].str.contains('Rising', na=False)) &
                    (df_res['Price Tightness (%)'] < 3.0) &
                    (df_res['Dist to 20D High (%)'].between(-8, 0))
                )
                # Apply price & float filter dari sidebar
                coil_mask &= (df_res['Last Price'] >= min_p) & (df_res['Last Price'] <= max_p)
                coil_mask &= (df_res['Free Float (%)'] <= max_ff)
                df_coil = df_res[coil_mask].copy()
                if not df_coil.empty:
                    df_coil['Entry Readiness Score'] = df_coil.apply(calc_entry_readiness, axis=1)
                    df_coil['Entry Readiness'] = df_coil['Entry Readiness Score'].apply(entry_readiness_label)
                    df_coil = df_coil.sort_values(['Entry Readiness Score', 'Composite Rank'], ascending=[False, False])
            else:
                df_coil = pd.DataFrame()

            if not df_coil.empty:
                coil_cols = [
                    'Kode Saham', 'Last Price', 'Value (Rp)', 'Entry Readiness', 'Entry Readiness Score',
                    'Composite Rank', 'Silent Score',
                    'ADX (14)', 'ADX Direction', 'ADX Trend', 'ADX Strength',
                    'Price Tightness (%)', 'Dist to 20D High (%)',
                    'OBV Trend', 'Vol Trend Ratio', 'Rel Vol (20D)',
                    'MFI (14D)', 'MFI Change 5D', 'RSI (14)',
                    'BB Squeeze', 'BB Width (%)',
                    'Free Float (%)', 'AvgVol20 (Lot)',
                    'Above MA20', 'Market RS',
                    'Chart Analysis', 'Visual Chart Analysis',
                ]
                cols_coil = [c for c in coil_cols if c in df_coil.columns]

                def apply_coil_style(df_styled):
                    styled = (df_styled
                        .map(style_entry_readiness, subset=['Entry Readiness Score'])
                        .map(style_silent_score,    subset=['Silent Score'])
                        .map(style_composite_rank,  subset=['Composite Rank'])
                        .map(style_bb_squeeze,      subset=['BB Squeeze'])
                        .map(style_obv_trend,       subset=['OBV Trend'])
                        .map(style_mfi,             subset=['MFI (14D)'])
                        .map(style_adx_trend,       subset=['ADX Trend'])
                        .map(style_adx_dir,         subset=['ADX Direction'])
                        .map(style_market_rs,       subset=['Market RS'])
                        .map(style_ma_filter,       subset=['Above MA20'])
                        .map(style_chart_analysis,  subset=['Chart Analysis'])
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
                    return styled

                st.dataframe(
                    apply_coil_style(df_coil[cols_coil].style),
                    use_container_width=True,
                    height=420,
                )

                # ── Ringkasan per kandidat ──
                st.markdown("#### 📋 Status Entry Readiness")
                for _, row in df_coil.iterrows():
                    er    = int(row.get('Entry Readiness Score', 0))
                    er_lbl = row.get('Entry Readiness', '⚪ Belum')
                    cr    = int(row.get('Composite Rank', 0))
                    sc    = int(row.get('Silent Score', 0))
                    pt    = float(row.get('Price Tightness (%)', 0))
                    adx   = float(row.get('ADX (14)', 0))
                    dist  = float(row.get('Dist to 20D High (%)', 0))
                    rv    = float(row.get('Rel Vol (20D)', 0))
                    mfi_c = float(row.get('MFI Change 5D', 0))

                    # Trigger breakdown
                    triggers = []
                    if rv > 2.0:    triggers.append(f"✅ Vol Spike ({rv:.1f}x)")
                    else:           triggers.append(f"⬜ Vol ({rv:.1f}x, butuh >2x)")
                    if mfi_c > 15:  triggers.append(f"✅ MFI Lonjak (+{mfi_c:.1f})")
                    else:           triggers.append(f"⬜ MFI Change (+{mfi_c:.1f}, butuh >15)")
                    if dist > -1.0: triggers.append(f"✅ Dekat/Breakout ({dist:.1f}%)")
                    else:           triggers.append(f"⬜ Dist to Resist ({dist:.1f}%, butuh >-1%)")

                    st.markdown(
                        f"**{row['Kode Saham']}** | Rp {row['Last Price']:,} | "
                        f"{er_lbl} ({er}/3 trigger) | "
                        f"Composite: **{cr}** | Silent: **{sc}** | "
                        f"ADX: {adx:.0f} | Tightness: {pt:.1f}%"
                    )
                    st.caption(" &nbsp;|&nbsp; ".join(triggers))
                    st.divider()

                # ── Chart ──
                st.markdown("#### 📈 Chart")
                ticker_list_coil = df_coil['Kode Saham'].tolist()
                default_idx_coil = ticker_list_coil.index(st.session_state.tv_ticker)                     if st.session_state.tv_ticker in ticker_list_coil else 0
                selected_tv_coil = st.selectbox(
                    "🔍 Pilih saham:", ticker_list_coil,
                    index=default_idx_coil, key="tv_select_coil"
                )
                if selected_tv_coil:
                    st.session_state.tv_ticker = selected_tv_coil
                    chart_mode_coil = st.radio(
                        "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                        key="chart_mode_coil", horizontal=True
                    )
                    if "Plotly" in chart_mode_coil:
                        show_plotly_candlestick(selected_tv_coil, chart_key=f"plotly_coil_{selected_tv_coil}", end_date=_end_d_render)
                    else:
                        show_tradingview_widget(selected_tv_coil)

                # ── Penjelasan ──
                with st.expander("📖 Cara Baca Coil Watch & Entry Readiness"):
                    st.markdown("""
**Coil Watch** — Saham yang memenuhi SEMUA kriteria berikut:
| Kriteria | Threshold | Arti |
|---|---|---|
| Silent Score | ≥ 7 | Akumulasi diam-diam sangat terdeteksi |
| Composite Rank | ≥ 8 | Skor gabungan tinggi |
| ADX | > 50 + Bullish | Tren kuat tersembunyi — paradoks dengan sideways |
| OBV | Rising ↑ | Volume beli masuk diam-diam secara kumulatif |
| Price Tightness | < 3% | Harga bergerak sangat sempit = pegas ditekan |
| Dist to Resistance | -8% s.d. 0% | Dekat resistance, tinggal sedikit trigger |

**Entry Readiness Score (0–3)** — Trigger nyata yang sudah muncul:
| Trigger | Kondisi | Arti |
|---|---|---|
| ✅ Volume Spike | Rel Vol > 2x | Uang besar masuk tiba-tiba — ini yang paling kuat |
| ✅ MFI Lonjak | MFI Change 5D > 15 | Tekanan beli masif dalam 5 hari terakhir |
| ✅ Breakout | Dist to Resist > -1% | Sudah atau hampir tembus resistance 20 hari |

**Interpretasi:**
- 🟢 **SIAP ENTRY (3/3)** — Semua trigger muncul. Konfirmasi dengan chart, lalu entry
- 🟡 **Hampir Siap (2/3)** — Pantau harian, alert di harga resistance
- 🟠 **Tunggu (1/3)** — Masuk watchlist, review tiap 2–3 hari
- ⚪ **Belum (0/3)** — Saham coil tapi belum ada trigger. Sabar
""")
            else:
                st.info(
                    "Tidak ada kandidat Coil Watch saat ini. "
                    "Kriteria: Silent Score ≥ 7 + Composite Rank ≥ 8 + ADX > 50 Bullish + "
                    "OBV Rising + Price Tightness < 3% + Dist to Resist antara -8% s.d. 0%."
                )

        # ═══════════════════════════════════════

        # ═══════════════════════════════════════
        # TAB PRE-EXPLOSION WATCH (v34)
        # ═══════════════════════════════════════
        with tab_explosion:
            st.subheader("💥 Pre-Explosion Watch — Energi Terakumulasi Belum Meledak (v34)")
            st.markdown("""
> **Filosofi:** Menangkap saham yang berada di fase **"mengisi energi"** sebelum pergerakan besar.
> Berbeda dengan Coil Watch (ADX sudah sangat kuat), tab ini justru mencari kondisi paradoks:
> **BB lebar** (volatilitas historis pernah tinggi) namun **harga sekarang sangat ketat** (Price Tightness < 3%) dan
> **ADX Flat** (energi terakumulasi, belum dilepas). Kombinasi ini terbukti dari backtest April–Juni 2026
> meningkat presisinya dari 26.7% → 42.9% lintas periode.
>
> 🎯 **Cara pakai:** Pantau harian. Entry setelah ada konfirmasi: Volume spike >2x, MFI naik >15 dalam 5 hari,
> atau harga mulai mendekati/menembus resistance 20D.
""")

            if not df_res.empty and 'BB Width Pct Rank' in df_res.columns:
                explosion_mask = (
                    (df_res['BB Width Pct Rank'] >= 0.75) &          # BB lebar (Q75+ dari 50 hari)
                    (df_res['Price Tightness (%)'] < 3.0) &           # Harga sideways sangat ketat
                    (df_res['ADX Trend'] == 'Flat') &                 # ADX stagnan — energi belum dilepas
                    (df_res['Above MA20'] == 'YA') &                  # Struktur harga masih sehat
                    (df_res['ADX Direction'].str.contains('Bullish', na=False))  # Bias masih bullish
                )
                explosion_mask &= (df_res['Last Price'] >= min_p) & (df_res['Last Price'] <= max_p)
                explosion_mask &= (df_res['Free Float (%)'] <= max_ff)
                df_expl = df_res[explosion_mask].copy()

                if not df_expl.empty:
                    # Hitung Explosion Score (0–5) untuk sorting
                    def calc_explosion_score(row):
                        score = 0
                        # Makin lebar BB relatif historisnya, makin tinggi energi terpendam
                        if row.get('BB Width Pct Rank', 0) >= 0.90:  score += 2
                        elif row.get('BB Width Pct Rank', 0) >= 0.75: score += 1
                        # Makin ketat harga, makin terkompres
                        if row.get('Price Tightness (%)', 99) < 1.5:  score += 2
                        elif row.get('Price Tightness (%)', 99) < 3.0: score += 1
                        # OBV Rising = akumulasi tersembunyi mendukung
                        if row.get('OBV Trend', '') == 'Rising ↑':    score += 1
                        # Float kecil = potensi ledak lebih besar
                        if row.get('Free Float (%)', 100) < 15:        score += 1
                        # Volume mulai naik diam-diam
                        if row.get('Vol Trend Ratio', 0) >= 1.5:       score += 1
                        return min(score, 5)

                    def explosion_score_label(v):
                        if v >= 4:   return "🔴 Kritis"
                        elif v >= 3: return "🟠 Siap"
                        elif v >= 2: return "🟡 Pantau"
                        else:        return "⚪ Awal"

                    def style_explosion_score(v):
                        try:
                            v = int(v)
                            if v >= 4:   return 'background-color:#ff4b4b;color:white;font-weight:bold'
                            elif v >= 3: return 'background-color:#ff9f43;color:white;font-weight:bold'
                            elif v >= 2: return 'background-color:#ffd32a;color:#333'
                            else:        return ''
                        except: return ''

                    def style_bb_pct_rank(v):
                        try:
                            v = float(v)
                            if v >= 0.90: return 'background-color:#e17055;color:white;font-weight:bold'
                            elif v >= 0.75: return 'background-color:#fab1a0;color:#333'
                            else: return ''
                        except: return ''

                    df_expl['Explosion Score'] = df_expl.apply(calc_explosion_score, axis=1)
                    df_expl['Explosion Label'] = df_expl['Explosion Score'].apply(explosion_score_label)
                    df_expl = df_expl.sort_values(['Explosion Score', 'BB Width Pct Rank'], ascending=[False, False])

                    expl_cols = [
                        'Kode Saham', 'Last Price', 'Value (Rp)', 'Explosion Label', 'Explosion Score',
                        'BB Width (%)', 'BB Width Pct Rank', 'Price Tightness (%)',
                        'ADX (14)', 'ADX Trend', 'ADX Direction',
                        'OBV Trend', 'Vol Trend Ratio', 'Rel Vol (20D)',
                        'MFI (14D)', 'MFI Change 5D', 'RSI (14)',
                        'Silent Score', 'Wyckoff Phase',
                        'Free Float (%)', 'Float Urgency',
                        'Above MA20', 'Dist to 20D High (%)',
                        'Market RS', 'Chart Analysis',
                    ]
                    cols_expl = [c for c in expl_cols if c in df_expl.columns]

                    def apply_explosion_style(df_styled):
                        styled = df_styled
                        if 'Explosion Score' in df_expl.columns:
                            styled = styled.map(style_explosion_score, subset=['Explosion Score'])
                        if 'BB Width Pct Rank' in df_expl.columns:
                            styled = styled.map(style_bb_pct_rank, subset=['BB Width Pct Rank'])
                        styled = (styled
                            .map(style_obv_trend,   subset=['OBV Trend'])
                            .map(style_silent_score, subset=['Silent Score'])
                            .map(style_mfi,          subset=['MFI (14D)'])
                            .map(style_adx_trend,    subset=['ADX Trend'])
                            .map(style_adx_dir,      subset=['ADX Direction'])
                            .map(style_market_rs,    subset=['Market RS'])
                            .map(style_ma_filter,    subset=['Above MA20'])
                            .map(style_chart_analysis, subset=['Chart Analysis'])
                            .format({
                                'Free Float (%)':       '{:.1f}%',
                                'MFI (14D)':            '{:.1f}',
                                'MFI Change 5D':        '{:+.1f}',
                                'RSI (14)':             '{:.1f}',
                                'ADX (14)':             '{:.1f}',
                                'BB Width (%)':         '{:.2f}%',
                                'BB Width Pct Rank':    '{:.2f}',
                                'Vol Trend Ratio':      '{:.2f}x',
                                'Price Tightness (%)':  '{:.2f}%',
                                'Dist to 20D High (%)': '{:.2f}%',
                                'Rel Vol (20D)':        '{:.2f}x',
                            }, na_rep="-")
                        )
                        return styled

                    st.dataframe(
                        apply_explosion_style(df_expl[cols_expl].style),
                        use_container_width=True,
                        height=420,
                    )

                    # ── Ringkasan per kandidat ──
                    st.markdown("#### 📋 Status per Kandidat")
                    for _, row in df_expl.iterrows():
                        es    = int(row.get('Explosion Score', 0))
                        el    = row.get('Explosion Label', '⚪ Awal')
                        pt    = float(row.get('Price Tightness (%)', 0))
                        bwpr  = float(row.get('BB Width Pct Rank', 0))
                        adx   = float(row.get('ADX (14)', 0))
                        rv    = float(row.get('Rel Vol (20D)', 0))
                        mfi_c = float(row.get('MFI Change 5D', 0))
                        dist  = float(row.get('Dist to 20D High (%)', 0))
                        obv   = row.get('OBV Trend', '')
                        ff    = float(row.get('Free Float (%)', 0))
                        vtr   = float(row.get('Vol Trend Ratio', 0))

                        signals = []
                        signals.append(f"{'✅' if bwpr >= 0.90 else '🟡'} BB Lebar (rank {bwpr:.0%} dari 50hr)")
                        signals.append(f"{'✅' if pt < 1.5 else '🟡'} Tightness {pt:.1f}% {'sangat ketat' if pt < 1.5 else 'ketat'}")
                        signals.append(f"{'✅' if obv == 'Rising ↑' else '⬜'} OBV {obv}")
                        signals.append(f"{'✅' if vtr >= 1.5 else '⬜'} Vol Trend {vtr:.1f}x")
                        signals.append(f"{'✅' if dist > -3.0 else '⬜'} Dist ke R: {dist:.1f}%")

                        st.markdown(
                            f"**{row['Kode Saham']}** | Rp {row['Last Price']:,} | "
                            f"{el} ({es}/5) | ADX: {adx:.0f} Flat | "
                            f"Float: {ff:.1f}%"
                        )
                        st.caption(" &nbsp;|&nbsp; ".join(signals))
                        st.divider()

                    # ── Chart ──
                    st.markdown("#### 📈 Chart")
                    ticker_list_expl = df_expl['Kode Saham'].tolist()
                    default_idx_expl = (ticker_list_expl.index(st.session_state.tv_ticker)
                                        if st.session_state.tv_ticker in ticker_list_expl else 0)
                    selected_tv_expl = st.selectbox(
                        "🔍 Pilih saham:", ticker_list_expl,
                        index=default_idx_expl, key="tv_select_expl"
                    )
                    if selected_tv_expl:
                        st.session_state.tv_ticker = selected_tv_expl
                        chart_mode_expl = st.radio(
                            "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                            key="chart_mode_expl", horizontal=True
                        )
                        if "Plotly" in chart_mode_expl:
                            show_plotly_candlestick(selected_tv_expl, chart_key=f"plotly_expl_{selected_tv_expl}", end_date=_end_d_render)
                        else:
                            show_tradingview_widget(selected_tv_expl)

                    with st.expander("📖 Cara Baca Pre-Explosion Watch"):
                        st.markdown("""
**Pre-Explosion Watch** — Saham yang memenuhi SEMUA kriteria berikut:

| Kriteria | Threshold | Arti |
|---|---|---|
| BB Width Pct Rank | ≥ 75% dari 50hr terakhir | BB historis pernah lebar — energi besar pernah ada |
| Price Tightness | < 3% | Harga sekarang sangat ketat — energi dikompres |
| ADX Trend | Flat | ADX stagnan — belum ada yang "menarik pelatuk" |
| ADX Direction | Bullish | Bias masih ke atas (DI+ > DI-) |
| Above MA20 | YA | Struktur harga sehat, tidak dalam downtrend |

**Explosion Score (0–5)** — Menilai seberapa "terisi" energinya:

| Kriteria | Poin | Penjelasan |
|---|---|---|
| BB Width Rank ≥ 90% | +2 | BB sangat lebar historis — energi sangat besar |
| BB Width Rank ≥ 75% | +1 | BB lebar — energi sedang |
| Tightness < 1.5% | +2 | Harga sangat-sangat ketat — pegas sangat tertekan |
| Tightness < 3.0% | +1 | Harga ketat |
| OBV Rising | +1 | Akumulasi tersembunyi terdeteksi |
| Free Float < 15% | +1 | Float kecil — ledakan lebih eksplosif |
| Vol Trend ≥ 1.5x | +1 | Volume mulai naik diam-diam |

**Label:**
- 🔴 **Kritis (4–5)** — Semua sinyal terisi. Bisa meledak kapan saja. Pantau sangat ketat
- 🟠 **Siap (3)** — Hampir semua sinyal ada. Alert di resistance
- 🟡 **Pantau (2)** — Sedang mengisi energi. Review setiap 2–3 hari
- ⚪ **Awal (0–1)** — Baru masuk kriteria dasar. Beri waktu

**Perbedaan dengan Coil Watch:**
Coil Watch mensyaratkan ADX > 50 (tren sudah sangat kuat). Pre-Explosion justru mencari ADX Flat —
kondisi di mana pasar belum "sadar" bahwa saham ini sedang diakumulasi. Ini adalah fase yang **lebih awal**
dari Coil Watch, dengan reward lebih besar dan risiko lebih tinggi.
""")

            else:
                st.info(
                    "Tidak ada kandidat Pre-Explosion Watch saat ini. "
                    "Kriteria: BB Width Rank ≥ 75% + Price Tightness < 3% + ADX Flat + Bullish + Above MA20."
                )

        # ═══════════════════════════════════════

        # ═══════════════════════════════════════
        # TAB WYCKOFF PHASES (v33)
        # ═══════════════════════════════════════
        with tab_wyckoff:
            st.subheader("🏛️ Wyckoff Phase Detector (v34)")
            st.markdown("""
> **Filosofi:** Wyckoff Accumulation adalah urutan 4 fase yang dilalui saham sebelum markup:
> **Phase A** (Selling Climax — panik jual + volume meledak) →
> **Phase B** (akumulasi diam-diam oleh smart money) →
> **Phase C** (Spring — fake breakdown, "shakeout" retail) →
> **Phase D** (Breakout valid + volume konfirmasi).
>
> 🎯 **Cara pakai:** Fokus pada saham dengan **Wyckoff Score ≥ 6** dan fase **Spring** atau **Markup**.
> Spring adalah entry terbaik — risiko kecil, potensi besar.
""")

            if not df_res.empty and 'Wyckoff Score' in df_res.columns:
                # ── Filter sidebar ──
                min_wyckoff = st.slider(
                    "Min Wyckoff Score", min_value=0, max_value=10, value=4,
                    help="0=semua saham | ≥4=ada sinyal | ≥6=setup matang | ≥8=sangat kuat"
                )
                filter_phase = st.multiselect(
                    "Filter Fase Wyckoff",
                    options=[
                        "Phase D — Markup 🚀", "Phase D — Breakout ⚡",
                        "Phase C — Spring 🌱", "Phase B — Akumulasi 🔍",
                        "Phase A — SC Detected 💥", "Pre-Wyckoff ❓"
                    ],
                    default=[],
                    help="Kosongkan untuk tampilkan semua fase",
                )

                df_w = df_res.copy()

                # Apply price & float filter
                if 'Last Price' in df_w.columns:
                    df_w = df_w[(df_w['Last Price'] >= min_p) & (df_w['Last Price'] <= max_p)]
                if 'Free Float (%)' in df_w.columns:
                    df_w = df_w[df_w['Free Float (%)'] <= max_ff]

                # Apply Wyckoff score filter
                df_w = df_w[df_w['Wyckoff Score'] >= min_wyckoff]

                # Apply phase filter (if any selected)
                if filter_phase and 'Wyckoff Phase' in df_w.columns:
                    df_w = df_w[df_w['Wyckoff Phase'].isin(filter_phase)]

                # Sort by Wyckoff Score desc
                df_w = df_w.sort_values('Wyckoff Score', ascending=False)

                # ── Phase distribution summary ──
                if not df_w.empty and 'Wyckoff Phase' in df_w.columns:
                    phase_counts = df_w['Wyckoff Phase'].value_counts()
                    cols_summary = st.columns(min(len(phase_counts), 5))
                    phase_colors = {
                        "Phase D — Markup 🚀":     "#00441b",
                        "Phase D — Breakout ⚡":   "#238b45",
                        "Phase C — Spring 🌱":     "#e6550d",
                        "Phase B — Akumulasi 🔍":  "#3182bd",
                        "Phase A — SC Detected 💥":"#756bb1",
                        "Pre-Wyckoff ❓":           "#969696",
                    }
                    for ci, (phase, count) in enumerate(phase_counts.items()):
                        if ci < len(cols_summary):
                            color = phase_colors.get(phase, "#636363")
                            cols_summary[ci].markdown(
                                f"<div style='background:{color};color:white;padding:8px 12px;"
                                f"border-radius:8px;text-align:center;font-size:13px'>"
                                f"<b>{count}</b><br>{phase}</div>",
                                unsafe_allow_html=True
                            )
                    st.markdown("")

                # ── Main table ──
                wyckoff_cols = [
                    'Kode Saham', 'Last Price', 'Value (Rp)', 'Wyckoff Score', 'Wyckoff Phase',
                    'SC Detected', 'SC Vol Ratio', 'SC Price Drop (%)',
                    'Spring Detected', 'Spring Strength',
                    'Shakeout Detected', 'Shakeout Type', 'Shakeout Score',
                    'Shakeout Verdict', 'Shakeout Confidence',
                    'Shakeout Vol Ratio', 'Shakeout Days Ago', 'Shakeout Warning',
                    'Silent Score', 'BB Squeeze', 'OBV Trend',
                    'Price Tightness (%)', 'Vol Trend Ratio',
                    '20D Breakout', 'Rel Vol (20D)',
                    'ADX (14)', 'ADX Trend', 'ADX Direction',
                    'MFI Change 5D', 'RSI (14)',
                    'Free Float (%)', 'AvgVol20 (Lot)',
                    'Wyckoff Reasons',
                ]
                cols_w = [c for c in wyckoff_cols if c in df_w.columns]

                if not df_w.empty:
                    def apply_wyckoff_style(df_styled):
                        cols_available = df_styled.data.columns.tolist()
                        styled = df_styled.format({
                            'Free Float (%)':       '{:.1f}%',
                            'MFI Change 5D':        '{:+.1f}',
                            'RSI (14)':             '{:.1f}',
                            'ADX (14)':             '{:.1f}',
                            'SC Vol Ratio':         '{:.2f}x',
                            'SC Price Drop (%)':    '{:.1f}%',
                            'Vol Trend Ratio':      '{:.2f}x',
                            'Price Tightness (%)':  '{:.2f}%',
                            'Rel Vol (20D)':        '{:.2f}x',
                        }, na_rep="-")

                        def _m(fn, col):
                            nonlocal styled
                            if col in cols_available:
                                styled = styled.map(fn, subset=[col])

                        _m(style_wyckoff_score,  'Wyckoff Score')
                        _m(style_wyckoff_phase,  'Wyckoff Phase')
                        _m(style_silent_score,   'Silent Score')
                        _m(style_bb_squeeze,     'BB Squeeze')
                        _m(style_obv_trend,      'OBV Trend')
                        _m(style_adx_trend,      'ADX Trend')
                        _m(style_adx_dir,        'ADX Direction')
                        _m(style_adx,            'ADX (14)')
                        _m(style_rel_vol,        'Rel Vol (20D)')
                        return styled

                    st.dataframe(
                        apply_wyckoff_style(df_w[cols_w].style),
                        use_container_width=True,
                        height=440,
                    )
                    st.caption(f"Menampilkan {len(df_w)} saham dengan Wyckoff Score ≥ {min_wyckoff}")

                    # ── Per-saham Wyckoff card ──
                    spring_candidates = df_w[df_w['Spring Detected'] == '🌱 Spring']
                    if not spring_candidates.empty:
                        st.markdown("#### 🌱 Spring Candidates — Entry Terbaik Wyckoff")
                        for _, row in spring_candidates.iterrows():
                            w_sc = int(row.get('Wyckoff Score', 0))
                            st.markdown(
                                f"**{row['Kode Saham']}** | Rp {row['Last Price']:,} | "
                                f"Wyckoff Score: **{w_sc}/10** | {row.get('Wyckoff Phase','')}"
                            )
                            reasons_text = row.get('Wyckoff Reasons', '')
                            if reasons_text:
                                for r in reasons_text.split(' | '):
                                    st.caption(r)
                            st.divider()

                    # ── v33: Shakeout Agresif Candidates ──
                    if 'Shakeout Detected' in df_w.columns:
                        shakeout_candidates = df_w[df_w['Shakeout Detected'].str.len() > 0]
                        if not shakeout_candidates.empty:
                            st.markdown("#### 🔥 Shakeout Candidates — Ritel Diguncang, Bandar Siap Naik")
                            st.caption("Shakeout terdeteksi via: Volume Spike + Pin Bar + Support Pierce + Multi-Day Reversal")
                            st.info(
                                "💡 **Cara baca:** Shakeout Score tinggi ≠ saham pasti naik. "
                                "Lihat **Verdict** dan **Confidence** untuk tahu apakah konteks Wyckoff mendukung.",
                                icon="ℹ️"
                            )
                            for _, row in shakeout_candidates.iterrows():
                                w_sc    = int(row.get('Wyckoff Score', 0))
                                sk      = int(row.get('Shakeout Score', 0))
                                stype   = row.get('Shakeout Type', '')
                                sdays   = row.get('Shakeout Days Ago', -1)
                                svol    = row.get('Shakeout Vol Ratio', 0)
                                verdict = row.get('Shakeout Verdict', '')
                                conf    = int(row.get('Shakeout Confidence', 0))
                                sw_text = row.get('Shakeout Warning', '—')
                                days_label = "hari ini" if sdays == 0 else f"{sdays}h lalu"

                                # Warna header kartu berdasarkan verdict
                                if 'VALID' in verdict:
                                    card_color = "#1a472a"
                                elif 'WASPADA' in verdict:
                                    card_color = "#7d4e00"
                                else:
                                    card_color = "#6b1a1a"

                                st.markdown(
                                    f"<div style='background:{card_color};padding:8px 12px;border-radius:6px;margin-bottom:4px'>"
                                    f"<b style='font-size:1.05em'>{row['Kode Saham']}</b> &nbsp;|&nbsp; "
                                    f"Rp {row['Last Price']:,} &nbsp;|&nbsp; "
                                    f"{row.get('Shakeout Detected','')} &nbsp;|&nbsp; "
                                    f"Tipe: <code>{stype}</code> &nbsp;|&nbsp; "
                                    f"Score: <b>{sk}/5</b> &nbsp;|&nbsp; {days_label} &nbsp;|&nbsp; "
                                    f"<b style='font-size:1.1em'>{verdict}</b>"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )

                                # Metrics row
                                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                                col_s1.metric("Shakeout Score", f"{sk}/5")
                                col_s2.metric("Wyckoff Score", f"{w_sc}/10")
                                col_s3.metric("Vol Ratio", f"{svol:.1f}×")
                                col_s4.metric("Confidence", f"{conf}%")

                                # Confidence bar
                                bar_color = "#2ecc71" if conf >= 70 else "#f39c12" if conf >= 45 else "#e74c3c"
                                st.markdown(
                                    f"<div style='background:#333;border-radius:4px;height:10px;margin:4px 0'>"
                                    f"<div style='background:{bar_color};width:{conf}%;height:10px;border-radius:4px'></div>"
                                    f"</div><small style='color:#aaa'>Confidence Akumulasi: {conf}%</small>",
                                    unsafe_allow_html=True
                                )

                                # Context warnings & supports
                                _ctx_full = compute_shakeout_context_warning(
                                    shakeout_score  = sk,
                                    wyckoff_score   = w_sc,
                                    silent_score    = int(row.get('Silent Score', 0)),
                                    obv_trend       = str(row.get('OBV Trend', '')),
                                    was_score       = int(row.get('WAS', 0)),
                                    adx_direction   = str(row.get('ADX Direction', '')),
                                    wyckoff_phase   = str(row.get('Wyckoff Phase', '')),
                                    vol_trend_ratio = float(row.get('Vol Trend Ratio', 1.0)),
                                    price_tightness = float(row.get('Price Tightness (%)', 5.0)),
                                    free_float      = float(row.get('Free Float (%)', 50.0)),
                                )

                                with st.expander(f"📋 Detail Konteks — {row['Kode Saham']}"):
                                    st.markdown(f"**🎯 Saran Tindakan:** {_ctx_full['action']}")
                                    if _ctx_full['supports']:
                                        st.markdown("**Faktor Pendukung:**")
                                        for s in _ctx_full['supports']:
                                            st.caption(s)
                                    if _ctx_full['warnings']:
                                        st.markdown("**⚠️ Peringatan:**")
                                        for w in _ctx_full['warnings']:
                                            st.caption(w)
                                    wyckoff_reasons = row.get('Wyckoff Reasons', '')
                                    if wyckoff_reasons:
                                        st.markdown("**Wyckoff Reasons:**")
                                        for r in wyckoff_reasons.split(' | '):
                                            st.caption(r)

                                st.divider()

                    # ── Chart ──
                    st.markdown("#### 📈 Chart")
                    ticker_list_w = df_w['Kode Saham'].tolist()
                    if ticker_list_w:
                        default_idx_w2 = (
                            ticker_list_w.index(st.session_state.tv_ticker)
                            if st.session_state.tv_ticker in ticker_list_w else 0
                        )
                        selected_tv_w2 = st.selectbox(
                            "🔍 Pilih saham:", ticker_list_w,
                            index=default_idx_w2, key="tv_select_wyckoff"
                        )
                        if selected_tv_w2:
                            st.session_state.tv_ticker = selected_tv_w2
                            chart_mode_w = st.radio(
                                "Mode Chart:", ["📊 Plotly Candlestick (Interaktif)", "📈 TradingView Widget"],
                                key="chart_mode_wyckoff", horizontal=True
                            )
                            if "Plotly" in chart_mode_w:
                                show_plotly_candlestick(selected_tv_w2, chart_key=f"plotly_wyckoff_{selected_tv_w2}", end_date=_end_d_render)
                            else:
                                show_tradingview_widget(selected_tv_w2)

                    # ── Penjelasan Wyckoff ──
                    with st.expander("📖 Panduan Membaca Tab Wyckoff Phases"):
                        st.markdown("""
**Wyckoff Score (0–10)** — Skor kelengkapan urutan fase:
| Score | Arti |
|---|---|
| 8–10 | Setup sangat matang — semua fase terkonfirmasi |
| 6–7  | Setup kuat — perhatikan dengan seksama |
| 4–5  | Ada sinyal akumulasi — masukkan watchlist |
| 0–3  | Belum ada pola Wyckoff jelas |

**Fase yang Dideteksi:**
| Fase | Label | Sinyal | Entry? |
|---|---|---|---|
| A | SC Detected 💥 | Volume meledak ≥3× + harga drop ≥15% + rejection candle | Terlalu dini |
| B | Akumulasi 🔍 | Silent Score ≥5 + BB Squeeze + OBV Rising | Akumulasi kecil |
| C | Spring 🌱 | Fake breakdown support + vol rendah + close balik | **Entry terbaik** |
| C | Shakeout 🔥⚡ | Vol spike / Pin-Bar / Support Pierce / Multi-Day reversal | **Entry terbaik (v33)** |
| D | Breakout ⚡ / Markup 🚀 | Breakout resistance + volume konfirmasi | Entry momentum |

| **Spring — Entry Terbaik:**
Spring terjadi ketika harga sesaat tembus support (shakeout retail), lalu langsung balik naik menutup di atas support, dengan volume lebih rendah dari rata-rata (lack of supply).
Ini adalah sinyal bahwa supply di pasar sudah habis — bandar sudah selesai kumpul.

**Shakeout Agresif (v33) — Tipe yang Tidak Tertangkap Spring Klasik:**
| Tipe | Ciri Khas |
|---|---|
| **Vol-Spike** | Volume ≥1.8× avg20 + lower wick panjang + close recovery (shakeout paksa dengan volume besar) |
| **Pin-Bar** | Lower wick ≥2.5× body + close di upper 70% candle (candlestick hammer/pin bar kuat) |
| **Support-Pierce** | Low tembus support hingga 6% + close kembali di atas (toleransi lebih lebar dari Spring) |
| **Multi-Day** | 2+ hari turun berturut, lalu reversal kuat dengan volume naik |
| **Shakeout Score (0–5)** | Makin tinggi = makin banyak konfirmasi pola shakeout. ≥4 = Kuat, <4 = Normal. **Bukan jaminan naik — lihat Verdict.** |
| **Shakeout Verdict** | 🟢 VALID = konteks akumulasi mendukung · 🟡 WASPADA = konteks campuran · 🔴 JEBAKAN = sinyal akumulasi lemah, hindari entry |
| **Shakeout Confidence** | 0–100%. Mengukur seberapa kuat konteks Wyckoff mendukung shakeout. ≥70% = kuat, 45–69% = moderat, <45% = berbahaya |
| **Shakeout Warning** | Peringatan spesifik: OBV Falling, Wyckoff lemah, ADX Bearish, dll. Jika ada peringatan merah — shakeout bisa jadi jebakan distribusi |
""")
                else:
                    st.info(
                        f"Tidak ada saham dengan Wyckoff Score ≥ {min_wyckoff}. "
                        "Coba turunkan minimum score atau jalankan ulang analisa."
                    )
            else:
                st.warning("Jalankan analisa terlebih dahulu untuk melihat Wyckoff Phase Detector.")

        # ═══════════════════════════════════════
        # TAB FLOAT ANALYSIS (v33) — Hitung Barang
        # ═══════════════════════════════════════
        with tab_float:
            st.subheader("🧮 Float Analysis v34 — Hitung Barang")
            st.caption(
                "Menggabungkan seluruh data yang sudah ada (Free Float, OBV, BB Squeeze, Silent Score, WAS, Price Tightness, dll) "
                "untuk menilai seberapa 'tipis' supply dan seberapa aktif bandar mengumpulkan barang."
            )

            if not df_res.empty:

                # ── Remora Score sudah dihitung di level atas (compute_remora_score, remora_label) ──
                df_float = df_res.copy()
                # Gunakan kolom yang sudah dihitung saat persiapan download, atau hitung ulang jika belum ada
                if 'Remora Score' not in df_float.columns:
                    df_float['Remora Score'] = df_float.apply(compute_remora_score, axis=1)
                    df_float['Remora Label'] = df_float['Remora Score'].apply(remora_label)

                # ── Sidebar filter ──
                st.markdown("#### ⚙️ Filter")
                fc1, fc2, fc3 = st.columns(3)
                min_remora = fc1.slider(
                    "Min Remora Score", 0, 10, 4,
                    key="float_remora_filter",
                    help="≥8 = PRIME, ≥6 = KUAT, ≥4 = PANTAU"
                )
                min_accel_filter = fc2.slider(
                    "Min Vol Accel (5D/20D)", 0.0, 10.0, 1.5, 0.1,
                    key="float_accel_filter",
                    help="≥2x = akumulasi mulai terdeteksi. ≥3x = kuat."
                )
                max_ff_float = fc3.slider(
                    "Max Free Float (%)", 1.0, 100.0, 40.0, 1.0,
                    key="float_ff_filter",
                    help="Semakin kecil float = semakin mudah digerakkan bandar"
                )

                show_float_all = st.checkbox(
                    "Abaikan semua filter (tampilkan semua saham)", value=False,
                    key="float_show_all"
                )

                if not show_float_all:
                    df_float = df_float[
                        (df_float['Remora Score'] >= min_remora) &
                        (df_float['Vol Accel (5D/20D)'].apply(
                            lambda x: float(x) if str(x).replace('.','').isdigit() else 0) >= min_accel_filter
                        ) &
                        (df_float['Free Float (%)'] <= max_ff_float)
                    ]

                df_float = df_float.sort_values('Remora Score', ascending=False)

                if not df_float.empty:

                    # ── Summary metrics ──
                    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                    prime_count  = (df_float['Remora Score'] >= 8).sum()
                    kuat_count   = ((df_float['Remora Score'] >= 6) & (df_float['Remora Score'] < 8)).sum()
                    kritis_count = (df_float['Float Urgency'].str.contains("KRITIS", na=False)).sum()
                    accel_max    = df_float['Vol Accel (5D/20D)'].apply(
                        lambda x: float(x) if str(x).replace('.','').replace('-','').isdigit() else 0
                    ).max()
                    top_ticker   = df_float.iloc[0]['Kode Saham'] if len(df_float) > 0 else "-"
                    col_m1.metric("🔥 PRIME (≥8)", f"{prime_count} saham")
                    col_m2.metric("✅ KUAT (≥6)", f"{kuat_count} saham")
                    col_m3.metric("🔴 Float KRITIS", f"{kritis_count} saham")
                    col_m4.metric("⚡ Accel Maks", f"{accel_max:.1f}x")
                    col_m5.metric("🏆 Top Remora", top_ticker)

                    st.markdown("---")

                    # ── Tabel utama Float Analysis ──
                    float_display_cols = [
                        'Kode Saham',
                        'Remora Score', 'Remora Label',
                        'Free Float (%)', 'Last Price', 'Value (Rp)',
                        'Vol Accel (5D/20D)', 'Float Urgency',
                        'OBV Trend', 'BB Squeeze', 'Price Tightness (%)',
                        'Silent Score', 'WAS', 'Wyckoff Phase',
                        'Vol Trend Ratio', 'Rel Vol (20D)',
                        'AvgVol20 (Lot)',
                        'Estimasi Lot Terkumpul', 'Float Lot Est',
                        '% Float Swept 5D',
                        'Divergence Warning', 'Dist to 20D High (%)',
                        'ADX Direction', 'Above MA20',
                        'Float Note',
                    ]
                    float_display_cols = [c for c in float_display_cols if c in df_float.columns]

                    styled_float = apply_full_style(
                        df_float[float_display_cols].style,
                        include_silent=True,
                    )
                    styled_float = styled_float.map(style_remora,       subset=['Remora Score'])
                    styled_float = styled_float.map(style_remora_label,  subset=['Remora Label'])

                    st.dataframe(styled_float, use_container_width=True, height=520)

                    # ── Ringkasan kandidat PRIME & KUAT ──
                    df_prime = df_float[df_float['Remora Score'] >= 6]
                    if not df_prime.empty:
                        st.markdown("#### 🎯 Ringkasan Kandidat Remora Terbaik")
                        for _, row in df_prime.iterrows():
                            accel_val = row.get('Vol Accel (5D/20D)', 0)
                            try:
                                accel_val = float(accel_val)
                            except Exception:
                                accel_val = 0.0
                            dtc = row.get('Estimasi Lot Terkumpul', '-')
                            lot_str = f"{int(dtc):,}" if isinstance(dtc, (int, float)) and dtc != '-' else str(dtc)
                            swept = row.get('% Float Swept 5D', '-')
                            st.markdown(
                                f"**{row['Kode Saham']}** "
                                f"| Remora: **{int(row['Remora Score'])}/10** {row['Remora Label']} "
                                f"| Float: **{row['Free Float (%)']:.1f}%** "
                                f"| Accel: **{accel_val:.1f}x** "
                                f"| OBV: {row.get('OBV Trend','-')} "
                                f"| BB: {row.get('BB Squeeze','-')} "
                                f"| Silent: {row.get('Silent Score','-')} "
                                f"| WAS: {row.get('WAS','-')} "
                                f"| Lot Terkumpul: **{lot_str}** lot "
                                f"| Swept: {swept}%"
                            )

                    # ── Panduan ──
                    with st.expander("📖 Panduan Membaca Remora Score & Float Analysis"):
                        st.markdown("""
**Remora Score (0–10)** — Skor kesiapan saham untuk diikuti sebagai remora:

| Score | Label | Artinya |
|---|---|---|
| 8–10 | 🔥 PRIME | Semua sinyal hijau — float tipis + akumulasi aktif + Wyckoff konfirmasi |
| 6–7  | ✅ KUAT  | Sinyal kuat, layak masuk watchlist prioritas |
| 4–5  | 👀 PANTAU | Ada sinyal awal, pantau 1–3 hari ke depan |
| 0–3  | ⬜ LEMAH | Belum ada sinyal cukup |

**Komponen Remora Score:**

*Tier 1 — Supply & Kecepatan Akumulasi (maks 4 poin):*
- Free Float < 15% → +2 | Float 15–25% → +1
- Vol Accel ≥ 3x → +2 | Vol Accel 2–3x → +1

*Tier 2 — Konfirmasi Akumulasi Tersembunyi (maks 4 poin):*
- OBV Rising ↑ → +1
- BB Squeeze aktif → +1
- Price Tightness < 3% → +1
- Silent Score ≥ 6 → +1

*Tier 3 — Wyckoff & Momentum (maks 2 poin):*
- WAS ≥ 7 → +1
- Wyckoff Phase = Akumulasi / Spring → +1

*Penalti:*
- Bearish Divergence → -1
- Rel Vol > 5x (sudah extended) → -1
- Dist to 20D High > -5% (terlalu dekat resistance) → -1

---

**Vol Accel (5D/20D)** — ADV 5 hari ÷ ADV 20 hari:
≥5x = 🔴 sangat agresif | 3–5x = 🟠 kuat | 2–3x = 🟡 mulai | <2x = normal

**Estimasi Lot Terkumpul** — Dihitung dari data yang sudah ada, tanpa perlu kolom `Total Saham`.
Formula: **Σ Volume 5 Hari − (ADV20 × 5)**. Mengukur "kelebihan" volume vs baseline normal —
proxy berapa lot yang kemungkinan sudah diserap bandar dalam 5 hari terakhir.
Nilai positif = ada akumulasi di atas kebiasaan normal. Semakin besar = semakin aktif penyerapan.
""")
                else:
                    st.info("Tidak ada saham yang memenuhi kriteria filter. Turunkan threshold atau centang 'Abaikan semua filter'.")
            else:
                st.warning("Jalankan analisa terlebih dahulu untuk melihat Float Analysis.")

        # TAB 4: SEMUA HASIL ANALISA
        # ═══════════════════════════════════════
        with tab4:
            st.subheader("🔍 Seluruh Hasil Analisa")

            # Sort option
            sort_options = ['Entry Readiness Score', 'Composite Rank', 'Early Momentum Score', 'Silent Score', 'MFI Change 5D', 'MFI (14D)', 'Rel Vol (20D)', 'ADX (14)']
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
                        show_plotly_candlestick(selected_tv_all, chart_key=f"plotly_tab4_{selected_tv_all}", end_date=_end_d_render)
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
                if "Upload CSV" in broker_mode and not broker_scores:
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
                            'Kode Saham', 'Moonstock Score', 'Last Price', 'Value (Rp)', 'Free Float (%)',
                            'Broker Score', 'Broker Signal', 'Smart Net Lot', 'Asing Net Lot',
                            'Early Momentum Score', 'Silent Score', 'Above MA20', 'Market RS',
                            'MFI (14D)', 'MFI Change 5D', 'ADX (14)', 'ADX Trend',
                            'Composite Rank', 'Chart Analysis',
                        ]
                        moon_cols = [c for c in moon_display_cols if c in df_moon_all.columns]

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
                                    show_plotly_candlestick(ticker, chart_key=f"plotly_moon_{ticker}", end_date=_end_d_render)
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
                    result   = ai_chart_analysis(selected_for_ai, end_date=_end_d_render)
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

                bt_note  = f" [Backtest: s.d. {_end_d_render.strftime('%d %b %Y')}]" if _end_d_render < date.today() else ""
                src_note = ("📸 Screenshot Yahoo Finance + data OHLCV" if has_ss else "📊 Data OHLCV saja (screenshot gagal)") + bt_note
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
        # Shortlist: gunakan df_res_filtered agar konsisten dengan UI (semua filter sidebar berlaku)
        df_s_dl = df_res_filtered[df_res_filtered['Kode Saham'].isin(shortlist)] if not df_res_filtered.empty else pd.DataFrame()

        # Pre-Breakout Watch: filter harga+float saja (sama seperti logika UI tab Pre-Breakout)
        if not df_res.empty:
            _w_raw = df_res[df_res['Kode Saham'].isin(prebreakout_list)].copy()
            if not _w_raw.empty:
                _w_mask = (
                    (_w_raw['Last Price'] >= min_p) &
                    (_w_raw['Last Price'] <= max_p) &
                    (_w_raw['Free Float (%)'] <= max_ff)
                )
                df_w_dl = _w_raw[_w_mask].copy()
            else:
                df_w_dl = pd.DataFrame()
        else:
            df_w_dl = pd.DataFrame()

        # Silent Accumulation: filter harga+float+BB Squeeze saja (sama seperti logika UI tab Silent)
        if not df_res.empty:
            _si_raw = df_res[df_res['Kode Saham'].isin(silent_list)].copy()
            if not _si_raw.empty:
                _si_mask = (
                    (_si_raw['Last Price'] >= min_p) &
                    (_si_raw['Last Price'] <= max_p) &
                    (_si_raw['Free Float (%)'] <= max_ff)
                )
                if silent_require_squeeze:
                    _si_mask &= _si_raw['BB Squeeze'].isin(['SQUEEZE 🔥', 'Sempit'])
                df_si_dl = _si_raw[_si_mask].copy()
            else:
                df_si_dl = pd.DataFrame()
        else:
            df_si_dl = pd.DataFrame()

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

        # ── Helper: parse CSS color string → xlsxwriter format dict ──
        def _css_to_xls_fmt(workbook, css_str):
            """Konversi CSS style string ke xlsxwriter cell format."""
            if not css_str:
                return None
            props = {}
            for part in css_str.split(';'):
                part = part.strip()
                if ':' not in part:
                    continue
                k, v = part.split(':', 1)
                k, v = k.strip().lower(), v.strip()
                if k == 'background-color':
                    # Tangani rgba → hex approximate
                    if v.startswith('rgba'):
                        nums = [float(x.strip()) for x in v[5:-1].split(',')]
                        r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
                        props['bg_color'] = f'#{r:02X}{g:02X}{b:02X}'
                    elif v.startswith('#') or v.startswith('rgb'):
                        if v.startswith('rgb('):
                            nums = [int(x.strip()) for x in v[4:-1].split(',')]
                            props['bg_color'] = f'#{nums[0]:02X}{nums[1]:02X}{nums[2]:02X}'
                        else:
                            # Named color fallback
                            named = {'white':'#FFFFFF','black':'#000000',
                                     'red':'#FF0000','green':'#008000',
                                     'darkred':'#8B0000','gray':'#808080'}
                            props['bg_color'] = named.get(v, v) if not v.startswith('#') else v
                elif k == 'color':
                    named = {'white':'#FFFFFF','black':'#000000',
                             'red':'#FF0000','green':'#008000',
                             'darkred':'#8B0000','gray':'#808080',
                             '#333':'#333333','#555':'#555555',
                             '#004d00':'#004D00','#042C53':'#042C53',
                             '#1a3a1a':'#1A3A1A'}
                    fc = named.get(v, v) if not v.startswith('#') else v
                    props['font_color'] = fc
                elif k == 'font-weight' and v == 'bold':
                    props['bold'] = True
            if not props:
                return None
            return workbook.add_format(props)

        # ── Tabel lengkap styling: (kolom → fungsi_style) ──
        _STYLE_MAP = {
            'MFI (14D)':             style_mfi,
            'Market RS':             style_market_rs,
            'PVA':                   style_pva,
            'Above MA20':            style_ma_filter,
            'Rel Vol (20D)':         style_rel_vol,
            'ADX (14)':              style_adx,
            'Divergence Warning':    style_divergence,
            'ADX Trend':             style_adx_trend,
            'ADX Direction':         style_adx_dir,
            'Chart Analysis':        style_chart_analysis,
            'Visual Chart Analysis': style_visual_chart,
            'Early Momentum Score':  style_early_momentum,
            'Pre-Breakout Watch':    style_prebreakout,
            'Silent Score':          style_silent_score,
            'BB Squeeze':            style_bb_squeeze,
            'OBV Trend':             style_obv_trend,
            'Composite Rank':        style_composite_rank,
            'Wyckoff Score':         style_wyckoff_score,
            'Wyckoff Phase':         style_wyckoff_phase,
            'WAS':                   style_was,
            'Jalur Masuk':           style_jalur_masuk,
            'Float Urgency':         style_float_urgency,
            'Vol Accel (5D/20D)':    style_vol_accel,
            'Estimasi Lot Terkumpul':style_accumulated_lot,
            'Broker Score':          style_broker_score,
            'Broker Signal':         style_broker_signal,
            'Entry Readiness Score': style_entry_readiness,
            'Remora Score':          style_remora,
            'Remora Label':          style_remora_label,
            'Moonstock Score':       style_moonstock_score,
        }

        def write_colored_sheet(writer, df, sheet_name):
            """Tulis DataFrame ke sheet Excel dengan warna sesuai tampilan Streamlit."""
            if df.empty:
                return
            workbook  = writer.book
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            worksheet = writer.sheets[sheet_name]

            # Format header
            hdr_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#1F3864', 'font_color': '#FFFFFF',
                'border': 1, 'text_wrap': True, 'valign': 'vcenter',
            })
            for col_idx, col_name in enumerate(df.columns):
                worksheet.write(0, col_idx, col_name, hdr_fmt)

            # Format default (border tipis, font normal)
            default_fmt = workbook.add_format({'border': 1})

            # Cache format agar tidak buat duplikat
            _fmt_cache = {}

            cols = df.columns.tolist()
            for row_idx, (_, row) in enumerate(df.iterrows(), start=1):
                for col_idx, col_name in enumerate(cols):
                    val = row[col_name]
                    css = ''
                    if col_name in _STYLE_MAP:
                        try:
                            css = _STYLE_MAP[col_name](val) or ''
                        except Exception:
                            css = ''
                    if css and css not in _fmt_cache:
                        fmt = _css_to_xls_fmt(workbook, css)
                        if fmt:
                            # Tambahkan border ke format berwarna
                            _fmt_cache[css] = workbook.add_format(
                                {**{'border': 1}, **{
                                    k: v for k, v in {
                                        'bg_color':   getattr(fmt, '_format_index', None),
                                    }.items() if v
                                }}
                            )
                            # Lebih simpel: re-parse saja
                            props = {'border': 1}
                            for part in css.split(';'):
                                part = part.strip()
                                if ':' not in part: continue
                                k2, v2 = part.split(':', 1)
                                k2, v2 = k2.strip().lower(), v2.strip()
                                if k2 == 'background-color':
                                    if v2.startswith('rgba'):
                                        nums = [float(x.strip()) for x in v2[5:-1].split(',')]
                                        r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
                                        props['bg_color'] = f'#{r:02X}{g:02X}{b:02X}'
                                    elif v2.startswith('#'):
                                        props['bg_color'] = v2
                                elif k2 == 'color':
                                    named = {'white':'#FFFFFF','black':'#000000',
                                             'red':'#FF0000','green':'#008000',
                                             'darkred':'#8B0000','gray':'#808080',
                                             '#333':'#333333','#555':'#555555',
                                             '#004d00':'#004D00','#042C53':'#042C53',
                                             '#1a3a1a':'#1A3A1A'}
                                    fc = named.get(v2, v2)
                                    props['font_color'] = fc if fc.startswith('#') else ('#' + fc.lstrip('#'))
                                elif k2 == 'font-weight' and v2 == 'bold':
                                    props['bold'] = True
                            _fmt_cache[css] = workbook.add_format(props)
                        else:
                            _fmt_cache[css] = default_fmt

                    cell_fmt = _fmt_cache.get(css, default_fmt)

                    # Tulis nilai sel
                    display_val = '' if pd.isna(val) else val
                    try:
                        worksheet.write(row_idx, col_idx, display_val, cell_fmt)
                    except Exception:
                        worksheet.write(row_idx, col_idx, str(display_val), cell_fmt)

            # Auto-lebar kolom (maks 40 karakter)
            for col_idx, col_name in enumerate(cols):
                max_len = max(
                    len(str(col_name)),
                    df[col_name].astype(str).str.len().max() if not df[col_name].empty else 0
                )
                worksheet.set_column(col_idx, col_idx, min(max_len + 2, 40))

            # Freeze baris header
            worksheet.freeze_panes(1, 0)

        def to_excel_report_v34(df_short, df_watch, df_silent, df_coil, df_expl, df_all, df_moon=None, df_float=None, df_shakeout=None):
            """Export Excel v34 — semua sheet berwarna sesuai tampilan Streamlit."""
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                write_colored_sheet(writer, df_short,  'Shortlist')
                if not df_watch.empty:
                    write_colored_sheet(writer, df_watch,  'Pre-Breakout Watch')
                if not df_silent.empty:
                    write_colored_sheet(writer, df_silent, 'Silent Accumulation')
                if not df_coil.empty:
                    write_colored_sheet(writer, df_coil,   'Coil Watch')
                if not df_expl.empty:
                    write_colored_sheet(writer, df_expl,   'Pre-Explosion Watch')
                if df_moon is not None and not df_moon.empty:
                    write_colored_sheet(writer, df_moon,   'Moonstock Radar')
                if df_float is not None and not df_float.empty:
                    write_colored_sheet(writer, df_float,  'Float Analysis')
                if df_shakeout is not None and not df_shakeout.empty:
                    write_colored_sheet(writer, df_shakeout, 'Shakeout Shortlist')
                write_colored_sheet(writer, df_all,    'Semua Analisa')
            return output.getvalue()

        df_moon_dl = df_res[df_res['Kode Saham'].isin(moonstock_list)] if moonstock_list and not df_res.empty else pd.DataFrame()
        # Coil Watch download dataframe
        if not df_res.empty and coil_list:
            df_coil_dl = df_res[df_res['Kode Saham'].isin(coil_list)].copy()
            if 'Entry Readiness Score' not in df_coil_dl.columns:
                df_coil_dl['Entry Readiness Score'] = df_coil_dl.apply(calc_entry_readiness, axis=1)
                df_coil_dl['Entry Readiness'] = df_coil_dl['Entry Readiness Score'].apply(entry_readiness_label)
            df_coil_dl = df_coil_dl.sort_values(['Entry Readiness Score', 'Composite Rank'], ascending=[False, False])
        else:
            df_coil_dl = pd.DataFrame()

        # Pre-Explosion Watch download dataframe
        if not df_res.empty and 'BB Width Pct Rank' in df_res.columns:
            _expl_mask = (
                (df_res['BB Width Pct Rank'] >= 0.75) &
                (df_res['Price Tightness (%)'] < 3.0) &
                (df_res['ADX Trend'] == 'Flat') &
                (df_res['Above MA20'] == 'YA') &
                (df_res['ADX Direction'].str.contains('Bullish', na=False))
            )
            _expl_mask &= (df_res['Last Price'] >= min_p) & (df_res['Last Price'] <= max_p)
            _expl_mask &= (df_res['Free Float (%)'] <= max_ff)
            df_expl_dl = df_res[_expl_mask].copy()
            if not df_expl_dl.empty:
                def _calc_expl_score_dl(row):
                    s = 0
                    if row.get('BB Width Pct Rank', 0) >= 0.90: s += 2
                    elif row.get('BB Width Pct Rank', 0) >= 0.75: s += 1
                    if row.get('Price Tightness (%)', 99) < 1.5: s += 2
                    elif row.get('Price Tightness (%)', 99) < 3.0: s += 1
                    if row.get('OBV Trend', '') == 'Rising ↑': s += 1
                    if row.get('Free Float (%)', 100) < 15: s += 1
                    if row.get('Vol Trend Ratio', 0) >= 1.5: s += 1
                    return min(s, 5)
                df_expl_dl['Explosion Score'] = df_expl_dl.apply(_calc_expl_score_dl, axis=1)
                df_expl_dl['Explosion Label'] = df_expl_dl['Explosion Score'].apply(
                    lambda v: "🔴 Kritis" if v >= 4 else ("🟠 Siap" if v >= 3 else ("🟡 Pantau" if v >= 2 else "⚪ Awal"))
                )
                df_expl_dl = df_expl_dl.sort_values(['Explosion Score', 'BB Width Pct Rank'], ascending=[False, False])
        else:
            df_expl_dl = pd.DataFrame()

        # ── Hitung Remora Score & Label untuk seluruh df_res (agar masuk Excel) ──
        if not df_res.empty:
            df_res['Remora Score'] = df_res.apply(compute_remora_score, axis=1)
            df_res['Remora Label'] = df_res['Remora Score'].apply(remora_label)
            # Kolom Float Analysis khusus — sort by Remora Score
            _float_cols = [
                'Kode Saham', 'Remora Score', 'Remora Label',
                'Free Float (%)', 'Last Price', 'Value (Rp)',
                'OBV Trend', 'BB Squeeze', 'Price Tightness (%)',
                'Silent Score', 'WAS', 'Wyckoff Phase',
                'Vol Trend Ratio', 'Rel Vol (20D)',
                'AvgVol20 (Lot)', 'Estimasi Lot Terkumpul', 'Float Lot Est',
                '% Float Swept 5D', 'Divergence Warning',
                'Dist to 20D High (%)', 'ADX Direction', 'Above MA20',
                'Float Note',
            ]
            _float_cols_avail = [c for c in _float_cols if c in df_res.columns]
            df_float_dl = df_res[_float_cols_avail].sort_values('Remora Score', ascending=False)
        else:
            df_float_dl = pd.DataFrame()

        # Shakeout Shortlist download dataframe (mirror filter Tab 1: Phase C + Above MA20 + Verdict VALID)
        _shk_dl_required = ['Wyckoff Phase', 'Above MA20', 'Shakeout Verdict', 'Shakeout Confidence']
        if not df_res.empty and all(c in df_res.columns for c in _shk_dl_required):
            _shk_conf_dl = st.session_state.get('min_shakeout_conf_tab1', 70)
            df_shk_dl = df_res.copy()
            if 'Last Price' in df_shk_dl.columns:
                df_shk_dl = df_shk_dl[(df_shk_dl['Last Price'] >= min_p) & (df_shk_dl['Last Price'] <= max_p)]
            if 'Free Float (%)' in df_shk_dl.columns:
                df_shk_dl = df_shk_dl[df_shk_dl['Free Float (%)'] <= max_ff]
            df_shk_dl = df_shk_dl[
                df_shk_dl['Wyckoff Phase'].astype(str).str.startswith('Phase C — Shakeout') &
                (df_shk_dl['Above MA20'] == 'YA') &
                df_shk_dl['Shakeout Verdict'].astype(str).str.contains('VALID') &
                (df_shk_dl['Shakeout Confidence'] >= _shk_conf_dl)
            ].sort_values(['Shakeout Confidence', 'Wyckoff Score'], ascending=False)
        else:
            df_shk_dl = pd.DataFrame()

        excel_data = to_excel_report_v34(df_s_dl, df_w_dl, df_si_dl, df_coil_dl, df_expl_dl, df_res, df_moon_dl, df_float_dl, df_shk_dl)

        # ── Nama file Excel disertai periode tanggal awal - akhir analisa ──
        _bulan_id = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
                     "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
        def _fmt_tgl_id(_d):
            return f"{_d.day} {_bulan_id[_d.month - 1]} {_d.year}"
        _periode_label = f"{_fmt_tgl_id(start_d)} - {_fmt_tgl_id(end_d)}"
        st.sidebar.download_button(
            label="📥 Download Report Excel v34",
            data=excel_data,
            file_name=f"Analisa_BEI_{_periode_label}_v36.xlsx",
            mime="application/vnd.ms-excel"
        )

        # ── Legenda ──
        with st.expander("📖 Legenda Indikator v34"):
            st.markdown("""
| Kolom | Penjelasan |
|---|---|
| **Shortlist Score** 🆕 | Skor 0–17 berbasis hit-rate empiris v25. Default threshold naik ke 13 di v28 (~8 saham selektif). Komponen: ADX zone, Dist dari High, MFI, MFI Change, Vol Trend, DI+, OBV, RS, BB Squeeze |
| **WAS** 🆕 | **Wyckoff Accumulation Score** (v27) — skor 0–10 berbasis 6 faktor akumulasi bandar. ≥9 = akumulasi sangat kuat (setara pola BSBK pre-terbang 80%). |
| **Jalur Masuk** 🆕 | **Momentum (SS)** = masuk via Shortlist Score tinggi. **🧲 Wyckoff Accum** = masuk via jalur akumulasi Wyckoff (WAS≥9 + ADX≥50 + OBV Rising + Phase B + dll). **Momentum + Wyckoff** = memenuhi kedua jalur. |
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
| **BB Width Pct Rank** 🆕 | Posisi lebar BB saat ini relatif 50 hari terakhir. ≥0.75 = BB lebar secara historis (energi besar). Digunakan di Pre-Explosion Watch |
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
| **Vol Accel (5D/20D)** 🆕 | Rasio ADV 5 hari / ADV 20 hari. ≥2x = akumulasi mulai terdeteksi. ≥3x = kuat. ≥5x = sangat agresif |
| **Float Urgency** 🆕 | 🔴KRITIS / 🟠TINGGI / 🟡SEDANG / 🟢RENDAH — tingkat urgensi berdasarkan kecepatan penyerapan float |
| **Estimasi Lot Terkumpul** 🆕 | Estimasi lot yang sudah diserap bandar dalam 5 hari terakhir. Formula: Σ Vol 5hr − ADV20×5. Selalu bisa dihitung tanpa data Total Saham |
| **% Float Swept 5D** 🆕 | Estimasi % float yang sudah tersapu dalam 5 hari terakhir |
| **Float Lot Est** 🆕 | Estimasi total float dalam lot (butuh kolom *Total Saham* di FreeFloat.xlsx) |

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
        f"📂 Database: **{loaded_file}** | Listed_share.xlsx: " + (f"✅ {_n_listed:,} emiten" if _has_listed else "❌ Tidak ditemukan") + "\n\n"
        "**Perubahan utama v21:**\n"
        "- 🆕 **Cache TTL 5 menit**: Data chart & OHLCV diperbarui setiap 5 menit\n"
        "- 🆕 **Live Signal Panel**: Sinyal teknikal dihitung ulang tiap 1 menit di bawah setiap chart\n"
        "- 🆕 **Tombol 🔄 Refresh Data**: Per saham, langsung clear cache & reload data terbaru\n"
        "- 🆕 **Auto-refresh saat market buka**: Opsional, tiap 5 menit (aktifkan di sidebar)\n"
        "- ✅ Semua fitur v20 dipertahankan (Broker Summary, Moonstock Radar, Visual Chart Analysis, Silent Accumulation, AI Chart Analysis)"
    )
