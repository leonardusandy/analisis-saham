"""Indeks dunia, komoditas, dan kurs dari Yahoo Finance.

Hasil: <DATA_KELUAR>/global.json
Simbol yang tidak tersedia di Yahoo dilewati (dicatat di log); data lama dipertahankan
bila pengambilan gagal.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

WIB = timezone(timedelta(hours=7))
BERKAS = cfg.KELUAR / "global.json"

# (simbol Yahoo, nama, satuan/keterangan)
DAFTAR = {
    "indeks": [
        ("^JKSE", "IHSG", "Indonesia"), ("^GSPC", "S&P 500", "Amerika Serikat"), ("^DJI", "Dow Jones 30", "Amerika Serikat"),
        ("^IXIC", "Nasdaq", "Amerika Serikat"), ("^HSI", "Hang Seng", "Hong Kong"), ("^N225", "Nikkei 225", "Jepang"),
        ("^KS11", "KOSPI", "Korea Selatan"), ("000001.SS", "Shanghai Composite", "Tiongkok"), ("^STI", "Straits Times", "Singapura"),
        ("^KLSE", "FTSE Bursa Malaysia KLCI", "Malaysia"), ("^BSESN", "Sensex", "India"),
        ("^FTSE", "FTSE 100", "Inggris"), ("^FCHI", "CAC 40", "Prancis"), ("^GDAXI", "DAX", "Jerman"), ("^AXJO", "ASX 200", "Australia"),
    ],
    "komoditas": [
        ("BZ=F", "Minyak Brent", "USD/barel"), ("CL=F", "Minyak WTI", "USD/barel"), ("NG=F", "Gas alam", "USD/MMBtu"),
        ("MTF=F", "Batu bara Newcastle", "USD/ton"), ("GC=F", "Emas", "USD/troy ons"), ("SI=F", "Perak", "USD/troy ons"),
        ("HG=F", "Tembaga", "USD/pon"), ("ALI=F", "Aluminium", "USD/ton"), ("PL=F", "Platinum", "USD/troy ons"),
        ("ZS=F", "Kedelai", "sen USD/bushel"), ("KC=F", "Kopi", "sen USD/pon"),
        ("CC=F", "Kakao", "USD/ton"), ("SB=F", "Gula", "sen USD/pon"), ("ZW=F", "Gandum", "sen USD/bushel"),
    ],
    "kurs": [
        ("IDR=X", "USD/IDR", "Rupiah per dolar AS"), ("EURIDR=X", "EUR/IDR", "Rupiah per euro"),
        ("CNYIDR=X", "CNY/IDR", "Rupiah per yuan"), ("JPYIDR=X", "JPY/IDR", "Rupiah per yen"),
        ("SGDIDR=X", "SGD/IDR", "Rupiah per dolar Singapura"), ("MYRIDR=X", "MYR/IDR", "Rupiah per ringgit"),
        ("AUDIDR=X", "AUD/IDR", "Rupiah per dolar Australia"), ("GBPIDR=X", "GBP/IDR", "Rupiah per pound"),
        ("SARIDR=X", "SAR/IDR", "Rupiah per riyal"), ("DX-Y.NYB", "Indeks dolar AS (DXY)", "terhadap 6 mata uang"),
    ],
}


def _f(x, d=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, d) if math.isfinite(x) else None


def main():
    import yfinance as yf

    lama = {}
    if BERKAS.exists():
        try:
            lama = {x["simbol"]: x for g in json.loads(BERKAS.read_text())["data"].values() for x in g}
        except Exception:  # noqa: BLE001
            lama = {}

    TURUNAN = {"CNYIDR=X": "CNY=X", "SARIDR=X": "SAR=X"}  # dihitung dari USD/IDR dibagi USD/XXX
    simbol = [s for g in DAFTAR.values() for s, _, _ in g] + list(TURUNAN.values())
    try:
        mentah = yf.download(simbol, period="1y", interval="1d", auto_adjust=False, group_by="ticker",
                             threads=True, progress=False)
    except Exception as e:  # noqa: BLE001
        print("  ! unduhan gagal:", e)
        mentah = None

    data, hilang = {}, []
    for grup, daftar in DAFTAR.items():
        data[grup] = []
        for s, nama, ket in daftar:
            try:
                c = mentah[s]["Close"].dropna()
                if len(c) < 2 and s in TURUNAN:
                    usd = mentah["IDR=X"]["Close"].dropna()
                    lain = mentah[TURUNAN[s]]["Close"].dropna()
                    c = (usd / lain).dropna()
                if len(c) < 2:
                    raise KeyError
            except Exception:  # noqa: BLE001
                if s in lama:
                    data[grup].append(lama[s])
                hilang.append(s)
                continue

            def ubah(n):
                return _f((c.iloc[-1] / c.iloc[-1 - n] - 1) * 100, 2) if len(c) > n and c.iloc[-1 - n] else None

            tahun = c.index[-1].year
            sblm = c[c.index.year < tahun]
            data[grup].append({
                "simbol": s, "nama": nama, "ket": ket,
                "tanggal": c.index[-1].strftime("%Y-%m-%d"),
                "akhir": _f(c.iloc[-1]), "ubah": _f(c.iloc[-1] - c.iloc[-2]), "ubah_pct": ubah(1),
                "ubah_5h": ubah(5), "ubah_20h": ubah(21), "ubah_60h": ubah(63),
                "ubah_ytd": _f((c.iloc[-1] / sblm.iloc[-1] - 1) * 100, 2) if len(sblm) else None,
                "riwayat": [{"t": i.strftime("%Y-%m-%d"), "c": _f(v)} for i, v in c.tail(130).items()],
            })
    BERKAS.write_text(json.dumps({"dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "data": data},
                                 ensure_ascii=False, separators=(",", ":")))
    n = sum(len(v) for v in data.values())
    print(f"Global: {n} simbol tersedia; tidak tersedia/terlambat: {hilang}")


if __name__ == "__main__":
    main()
