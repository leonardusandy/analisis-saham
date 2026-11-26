"""Perhitungan indikator, skor kandidat, level transaksi, dan uji balik.

Semua fungsi di sini hanya memakai pandas/numpy sehingga bisa diuji tanpa internet.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import config as cfg


# ---------------------------------------------------------------------------
# Fraksi harga BEI
# ---------------------------------------------------------------------------
def fraksi(harga: float) -> int:
    if harga < 200:
        return 1
    if harga < 500:
        return 2
    if harga < 2000:
        return 5
    if harga < 5000:
        return 10
    return 25


def bulatkan(harga: float, arah: str = "bawah") -> float:
    """Bulatkan harga ke fraksi BEI terdekat."""
    if harga is None or not math.isfinite(harga) or harga <= 0:
        return float("nan")
    f = fraksi(harga)
    if arah == "atas":
        return float(math.ceil(harga / f) * f)
    return float(math.floor(harga / f) * f)


# ---------------------------------------------------------------------------
# Indikator
# ---------------------------------------------------------------------------
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    naik = delta.clip(lower=0)
    turun = -delta.clip(upper=0)
    rata_naik = naik.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rata_turun = turun.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = rata_naik / rata_turun.replace(0, np.nan)
    hasil = 100 - 100 / (1 + rs)
    return hasil.fillna(100.0).where(rata_naik.notna())


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def tambah_indikator(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["EMA12"] = c.ewm(span=12, adjust=False).mean()
    df["EMA26"] = c.ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_SIG"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIG"]
    std = c.rolling(20).std()
    df["BB_ATAS"] = df["SMA20"] + 2 * std
    df["BB_BAWAH"] = df["SMA20"] - 2 * std
    df["RSI"] = rsi(c)
    df["ATR"] = atr(df)
    df["VOL_RATA20"] = df["Volume"].rolling(20).mean().shift(1)
    df["RASIO_VOL"] = df["Volume"] / df["VOL_RATA20"]
    df["NILAI"] = df["Close"] * df["Volume"]
    df["NILAI_RATA20"] = df["NILAI"].rolling(20).mean()
    df["TERTINGGI20"] = df["High"].rolling(20).max().shift(1)
    rentang = (df["High"] - df["Low"]).replace(0, np.nan)
    df["POSISI_TUTUP"] = ((df["Close"] - df["Low"]) / rentang).fillna(0.5)
    df["PERUBAHAN"] = c.pct_change() * 100
    return df


# ---------------------------------------------------------------------------
# Skor kandidat
# ---------------------------------------------------------------------------
def skor_baris(df: pd.DataFrame) -> pd.DataFrame:
    """Hitung skor setiap hari (dipakai untuk hari ini dan uji balik)."""
    s = pd.DataFrame(index=df.index)
    s["tren"] = ((df["Close"] > df["SMA20"]) & (df["SMA20"] > df["SMA50"])).astype(int) * 2
    s["tembus20"] = (df["Close"] > df["TERTINGGI20"]).astype(int) * 2
    s["volume"] = np.select(
        [df["RASIO_VOL"] >= 2.5, df["RASIO_VOL"] >= 1.5], [2, 1], default=0
    )
    rsi_naik_dari_jenuh = (df["RSI"] > 30) & (df["RSI"].rolling(3).min().shift(1) <= 30)
    s["rsi_pulih"] = rsi_naik_dari_jenuh.astype(int) * 2
    s["momentum"] = ((df["RSI"] >= 50) & (df["RSI"] <= 70)).astype(int)
    macd_silang = (df["MACD_HIST"] > 0) & (df["MACD_HIST"].shift(1) <= 0)
    macd_silang = macd_silang | macd_silang.shift(1, fill_value=False)
    s["macd"] = macd_silang.astype(int) * 2
    s["tutup_kuat"] = (df["POSISI_TUTUP"] >= 0.7).astype(int)
    s["jenuh_beli"] = np.where(df["RSI"] > 75, -2, 0)
    s["naik_berlebihan"] = np.where(df["PERUBAHAN"] > 15, -2, 0)
    s["total"] = s.sum(axis=1)
    likuid = df["NILAI_RATA20"] >= cfg.NILAI_TRANSAKSI_MINIMAL
    s["likuid"] = likuid
    return s


ALASAN = {
    "tren": "Tren naik (harga > MA20 > MA50)",
    "tembus20": "Menembus harga tertinggi 20 hari",
    "volume": "Volume melonjak",
    "rsi_pulih": "RSI pulih dari jenuh jual",
    "momentum": "Momentum sehat (RSI 50–70)",
    "macd": "MACD baru silang naik",
    "tutup_kuat": "Ditutup dekat harga tertinggi hari ini",
    "jenuh_beli": "Peringatan: RSI jenuh beli (>75)",
    "naik_berlebihan": "Peringatan: naik >15% dalam sehari",
}


def level_transaksi(close: float, nilai_atr: float) -> dict:
    masuk = bulatkan(close, "bawah")
    stop = bulatkan(masuk - cfg.KALI_ATR_STOP * nilai_atr, "bawah")
    target = bulatkan(masuk + cfg.KALI_ATR_TARGET * nilai_atr, "atas")
    if not all(map(math.isfinite, [masuk, stop, target])) or masuk <= 0:
        return {}
    untung = (target * (1 - cfg.BIAYA_JUAL) - masuk * (1 + cfg.BIAYA_BELI)) / (masuk * (1 + cfg.BIAYA_BELI))
    rugi = (stop * (1 - cfg.BIAYA_JUAL) - masuk * (1 + cfg.BIAYA_BELI)) / (masuk * (1 + cfg.BIAYA_BELI))
    return {
        "masuk": masuk,
        "stop": stop,
        "target": target,
        "untung_bersih_pct": round(untung * 100, 2),
        "rugi_bersih_pct": round(rugi * 100, 2),
        "rasio": round(abs(untung / rugi), 2) if rugi else None,
    }


# ---------------------------------------------------------------------------
# Uji balik
# ---------------------------------------------------------------------------
def uji_balik(df: pd.DataFrame, skor: pd.DataFrame) -> list[dict]:
    """Simulasi: sinyal muncul di hari t, beli di harga pembukaan t+1.

    Posisi ditutup saat menyentuh target atau batas rugi, atau di harga penutupan
    hari ke-N. Jika target dan batas rugi tersentuh di hari yang sama, dianggap
    kena batas rugi (asumsi konservatif). Hasil sudah dipotong biaya.
    """
    hasil = []
    o, h, l, c, a = (df[k].to_numpy() for k in ["Open", "High", "Low", "Close", "ATR"])
    total = skor["total"].to_numpy()
    likuid = skor["likuid"].to_numpy()
    tanggal = df.index
    n = len(df)
    i = 60
    while i < n - 1:
        if total[i] >= cfg.SKOR_MINIMAL and likuid[i] and math.isfinite(a[i]):
            masuk = o[i + 1]
            if not (math.isfinite(masuk) and masuk > 0):
                i += 1
                continue
            stop = masuk - cfg.KALI_ATR_STOP * a[i]
            target = masuk + cfg.KALI_ATR_TARGET * a[i]
            keluar, cara, j_akhir = None, None, None
            for j in range(i + 1, min(i + 1 + cfg.HARI_PEGANG_MAKS, n)):
                if l[j] <= stop:
                    keluar, cara, j_akhir = stop, "stop", j
                    break
                if h[j] >= target:
                    keluar, cara, j_akhir = target, "target", j
                    break
            if keluar is None:
                j_akhir = min(i + cfg.HARI_PEGANG_MAKS, n - 1)
                keluar, cara = c[j_akhir], "waktu"
            beli = masuk * (1 + cfg.BIAYA_BELI)
            jual = keluar * (1 - cfg.BIAYA_JUAL)
            hasil.append(
                {
                    "tanggal": tanggal[i].strftime("%Y-%m-%d"),
                    "skor": int(total[i]),
                    "hasil_pct": round((jual - beli) / beli * 100, 2),
                    "cara": cara,
                }
            )
            i = j_akhir + 1  # tidak membuka posisi baru sebelum posisi lama selesai
        else:
            i += 1
    return hasil


def ringkas_uji(transaksi: list[dict]) -> dict:
    if not transaksi:
        return {"jumlah": 0}
    r = np.array([t["hasil_pct"] for t in transaksi])
    menang = r[r > 0]
    kalah = r[r <= 0]
    return {
        "jumlah": int(len(r)),
        "persen_menang": round(len(menang) / len(r) * 100, 1),
        "rata_hasil_pct": round(float(r.mean()), 2),
        "rata_menang_pct": round(float(menang.mean()), 2) if len(menang) else 0,
        "rata_kalah_pct": round(float(kalah.mean()), 2) if len(kalah) else 0,
        "total_hasil_pct": round(float(r.sum()), 2),
        "kena_target": int(sum(t["cara"] == "target" for t in transaksi)),
        "kena_stop": int(sum(t["cara"] == "stop" for t in transaksi)),
        "habis_waktu": int(sum(t["cara"] == "waktu" for t in transaksi)),
    }


# ---------------------------------------------------------------------------
# Analisis satu saham
# ---------------------------------------------------------------------------
def _f(x, d=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, d) if math.isfinite(x) else None


def analisis_saham(kode: str, df: pd.DataFrame) -> tuple[dict, dict] | None:
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[df["Close"] > 0]
    if len(df) < 70:
        return None
    df = tambah_indikator(df)
    skor = skor_baris(df)
    akhir = df.iloc[-1]
    s_akhir = skor.iloc[-1]

    alasan = [ALASAN[k] for k in ALASAN if s_akhir[k] != 0]
    level = level_transaksi(akhir["Close"], akhir["ATR"])
    transaksi = uji_balik(df, skor)

    ringkas = {
        "kode": kode,
        "tanggal": df.index[-1].strftime("%Y-%m-%d"),
        "tutup": _f(akhir["Close"], 0),
        "perubahan_pct": _f(akhir["PERUBAHAN"]),
        "volume": int(akhir["Volume"]) if math.isfinite(akhir["Volume"]) else None,
        "rasio_vol": _f(akhir["RASIO_VOL"]),
        "nilai_rata20_miliar": _f(akhir["NILAI_RATA20"] / 1e9, 1),
        "rsi": _f(akhir["RSI"], 1),
        "atr": _f(akhir["ATR"], 1),
        "sma20": _f(akhir["SMA20"], 0),
        "sma50": _f(akhir["SMA50"], 0),
        "skor": int(s_akhir["total"]),
        "likuid": bool(s_akhir["likuid"]),
        "alasan": alasan,
        "level": level,
        "uji_balik": ringkas_uji(transaksi),
    }

    bagian = df.tail(250)
    detail = {
        "kode": kode,
        "lilin": [
            {
                "t": idx.strftime("%Y-%m-%d"),
                "o": _f(r["Open"], 0),
                "h": _f(r["High"], 0),
                "l": _f(r["Low"], 0),
                "c": _f(r["Close"], 0),
                "v": int(r["Volume"]) if math.isfinite(r["Volume"]) else 0,
            }
            for idx, r in bagian.iterrows()
        ],
        "indikator": {
            k: [_f(v) for v in bagian[k].tolist()]
            for k in ["SMA20", "SMA50", "BB_ATAS", "BB_BAWAH", "RSI", "MACD", "MACD_SIG", "MACD_HIST"]
        },
        "skor_harian": [int(v) for v in skor["total"].tail(250).tolist()],
        "riwayat_sinyal": transaksi[-30:],
        "ringkas": ringkas,
    }
    return ringkas, detail
