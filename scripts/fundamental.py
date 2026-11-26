"""Ambil data fundamental, laporan keuangan ringkas, dan riwayat dividen.

Hasil: docs/data/fundamental.json (rasio kunci semua saham)
       docs/data/fundamental/<KODE>.json (detail per saham)
Jika sebuah saham gagal diambil, data lamanya dipertahankan.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

FOLDER = Path(__file__).resolve().parent.parent / "docs" / "data"
WIB = timezone(timedelta(hours=7))

SEKTOR = {
    "Financial Services": "Keuangan",
    "Basic Materials": "Bahan Baku",
    "Energy": "Energi",
    "Consumer Defensive": "Barang Konsumen Primer",
    "Consumer Cyclical": "Barang Konsumen Nonprimer",
    "Communication Services": "Telekomunikasi & Media",
    "Industrials": "Perindustrian",
    "Utilities": "Utilitas",
    "Real Estate": "Properti",
    "Healthcare": "Kesehatan",
    "Technology": "Teknologi",
}


def angka(x, d=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, d) if math.isfinite(x) else None


def baris_laporan(df, nama_baris: list[str], n: int) -> dict:
    """Ambil beberapa baris dari tabel laporan keuangan yfinance."""
    if df is None or getattr(df, "empty", True):
        return {"periode": [], "data": {}}
    kolom = list(df.columns)[:n][::-1]  # urut dari lama ke baru
    hasil = {"periode": [c.strftime("%Y-%m-%d") for c in kolom], "data": {}}
    for label, kandidat in nama_baris:
        for k in kandidat:
            if k in df.index:
                hasil["data"][label] = [angka(df.loc[k, c], 0) for c in kolom]
                break
    return hasil


LAPORAN_LABA = [
    ("Pendapatan", ["Total Revenue", "Operating Revenue"]),
    ("Laba kotor", ["Gross Profit"]),
    ("Laba usaha", ["Operating Income"]),
    ("Laba bersih", ["Net Income Common Stockholders", "Net Income"]),
    ("Laba per saham", ["Diluted EPS", "Basic EPS"]),
]
NERACA = [
    ("Total aset", ["Total Assets"]),
    ("Total liabilitas", ["Total Liabilities Net Minority Interest"]),
    ("Ekuitas", ["Stockholders Equity", "Common Stock Equity"]),
    ("Kas", ["Cash And Cash Equivalents"]),
    ("Utang berbunga", ["Total Debt"]),
]
ARUS_KAS = [
    ("Arus kas operasi", ["Operating Cash Flow"]),
    ("Belanja modal", ["Capital Expenditure"]),
    ("Arus kas bebas", ["Free Cash Flow"]),
    ("Dividen dibayar", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
]


def persen(x):
    """yfinance kadang memberi 0,028 dan kadang 2,8 untuk 2,8%."""
    x = angka(x)
    if x is None:
        return None
    return round(x * 100, 2) if abs(x) < 1.5 else round(x, 2)


def ambil_satu(kode: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(f"{kode}.JK")
    info = t.info or {}
    ringkas = {
        "kode": kode,
        "nama": info.get("longName") or info.get("shortName") or kode,
        "sektor": SEKTOR.get(info.get("sector"), info.get("sector") or "Lainnya"),
        "industri": info.get("industry"),
        "kapitalisasi": angka(info.get("marketCap"), 0),
        "per": angka(info.get("trailingPE"), 2),
        "per_maju": angka(info.get("forwardPE"), 2),
        "pbv": angka(info.get("priceToBook"), 2),
        "roe": persen(info.get("returnOnEquity")),
        "roa": persen(info.get("returnOnAssets")),
        "der": angka((info.get("debtToEquity") or 0) / 100, 2) if info.get("debtToEquity") is not None else None,
        "margin_laba": persen(info.get("profitMargins")),
        "tumbuh_pendapatan": persen(info.get("revenueGrowth")),
        "tumbuh_laba": persen(info.get("earningsGrowth")),
        "imbal_dividen": persen(info.get("dividendYield")),
        "eps": angka(info.get("trailingEps"), 2),
        "nilai_buku": angka(info.get("bookValue"), 2),
        "beta": angka(info.get("beta"), 2),
        "tertinggi_52m": angka(info.get("fiftyTwoWeekHigh"), 0),
        "terendah_52m": angka(info.get("fiftyTwoWeekLow"), 0),
        "jumlah_saham": angka(info.get("sharesOutstanding"), 0),
        "situs": info.get("website"),
    }
    detail = dict(ringkas)
    detail["profil"] = info.get("longBusinessSummary")
    for nama, fungsi, n in [
        ("laba_rugi_tahunan", lambda: t.income_stmt, 4),
        ("laba_rugi_kuartal", lambda: t.quarterly_income_stmt, 6),
    ]:
        try:
            detail[nama] = baris_laporan(fungsi(), LAPORAN_LABA, n)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {kode} {nama}: {e}")
    for nama, fungsi, baris in [
        ("neraca_tahunan", lambda: t.balance_sheet, NERACA),
        ("arus_kas_tahunan", lambda: t.cashflow, ARUS_KAS),
    ]:
        try:
            detail[nama] = baris_laporan(fungsi(), baris, 4)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {kode} {nama}: {e}")
    try:
        div = t.dividends
        detail["dividen"] = [
            {"t": i.strftime("%Y-%m-%d"), "nilai": angka(v, 2)} for i, v in div.tail(20).items()
        ]
    except Exception as e:  # noqa: BLE001
        print(f"  ! {kode} dividen: {e}")
        detail["dividen"] = []
    return ringkas, detail


def main():
    (FOLDER / "fundamental").mkdir(parents=True, exist_ok=True)
    berkas_ringkas = FOLDER / "fundamental.json"
    lama = {}
    if berkas_ringkas.exists():
        try:
            lama = {s["kode"]: s for s in json.loads(berkas_ringkas.read_text())["saham"]}
        except Exception:  # noqa: BLE001
            lama = {}

    hasil, gagal = {}, []
    for kode in cfg.SAHAM:
        for coba in range(2):
            try:
                ringkas, detail = ambil_satu(kode)
                hasil[kode] = ringkas
                (FOLDER / "fundamental" / f"{kode}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
                )
                break
            except Exception as e:  # noqa: BLE001
                print(f"  ! {kode} percobaan {coba + 1}: {e}")
                time.sleep(5)
        else:
            gagal.append(kode)
            if kode in lama:
                hasil[kode] = lama[kode]
        time.sleep(0.7)

    berkas_ringkas.write_text(
        json.dumps(
            {"dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "saham": list(hasil.values())},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    print(f"Fundamental: {len(hasil) - len(gagal)} berhasil, {len(gagal)} gagal {gagal}")


if __name__ == "__main__":
    main()
