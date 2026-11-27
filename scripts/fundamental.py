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

FOLDER = cfg.KELUAR
MAKS_PER_JALAN = 120      # jumlah saham yang diperbarui per hari (bergilir)
UMUR_MAKS_HARI = 6        # data fundamental dianggap basi setelah sekian hari
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


# ---------------------------------------------------------------------------
# Piotroski F-Score (0-9) dan Beneish M-Score, dari laporan keuangan tahunan (2 tahun terakhir)
# ---------------------------------------------------------------------------
def _ambil(df, nama: list[str], kol):
    if df is None or getattr(df, "empty", True) or kol >= len(df.columns):
        return None
    for n in nama:
        if n in df.index:
            v = angka(df.iloc[:, kol].get(n) if hasattr(df.iloc[:, kol], "get") else df.loc[n].iloc[kol])
            if v is not None:
                return v
    return None


def hitung_skor(inc, bs, cf, keuangan: bool = False) -> dict:
    """Mengembalikan piotroski (jumlah syarat lolos), piotroski_terdata (jumlah syarat yang bisa dihitung),
    dan beneish (M-Score 8 variabel; tidak dihitung untuk sektor keuangan)."""
    def v(df, nama, t):
        return _ambil(df, nama, t)
    NI = ["Net Income Common Stockholders", "Net Income"]
    TA = ["Total Assets"]
    CFO = ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]
    LTD = ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]
    CA, CL = ["Current Assets"], ["Current Liabilities"]
    SH = ["Ordinary Shares Number", "Share Issued"]
    REV = ["Total Revenue", "Operating Revenue"]
    GP = ["Gross Profit"]
    COGS = ["Cost Of Revenue", "Reconciled Cost Of Revenue"]
    AR = ["Accounts Receivable", "Receivables", "Gross Accounts Receivable"]
    PPE = ["Net PPE"]
    SEC = ["Available For Sale Securities", "Investmentin Financial Assets", "Other Short Term Investments"]
    DEP = ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]
    SGA = ["Selling General And Administration"]

    def bagi(a, b):
        return a / b if a is not None and b not in (None, 0) else None

    syarat = []
    ni0, ni1 = v(inc, NI, 0), v(inc, NI, 1)
    ta0, ta1, ta2 = v(bs, TA, 0), v(bs, TA, 1), v(bs, TA, 2)
    cfo0 = v(cf, CFO, 0)
    roa0, roa1 = bagi(ni0, ta1 or ta0), bagi(ni1, ta2 or ta1)
    syarat.append(None if roa0 is None else roa0 > 0)                                  # 1 ROA positif
    syarat.append(None if cfo0 is None else cfo0 > 0)                                  # 2 arus kas operasi positif
    syarat.append(None if roa0 is None or roa1 is None else roa0 > roa1)               # 3 ROA naik
    syarat.append(None if cfo0 is None or ni0 is None else cfo0 > ni0)                 # 4 kualitas laba
    lev0, lev1 = bagi(v(bs, LTD, 0) or 0.0, ta0), bagi(v(bs, LTD, 1) or 0.0, ta1)
    syarat.append(None if lev0 is None or lev1 is None else lev0 <= lev1)              # 5 utang jangka panjang turun
    cr0, cr1 = bagi(v(bs, CA, 0), v(bs, CL, 0)), bagi(v(bs, CA, 1), v(bs, CL, 1))
    syarat.append(None if cr0 is None or cr1 is None else cr0 > cr1)                   # 6 likuiditas membaik
    sh0, sh1 = v(bs, SH, 0), v(bs, SH, 1)
    syarat.append(None if sh0 is None or sh1 is None else sh0 <= sh1 * 1.001)          # 7 tidak menerbitkan saham baru
    rev0, rev1 = v(inc, REV, 0), v(inc, REV, 1)
    gm0, gm1 = bagi(v(inc, GP, 0), rev0), bagi(v(inc, GP, 1), rev1)
    syarat.append(None if gm0 is None or gm1 is None else gm0 > gm1)                   # 8 margin kotor naik
    at0, at1 = bagi(rev0, ta1 or ta0), bagi(rev1, ta2 or ta1)
    syarat.append(None if at0 is None or at1 is None else at0 > at1)                   # 9 perputaran aset naik
    ada = [x for x in syarat if x is not None]
    hasil = {"piotroski": sum(ada) if ada else None, "piotroski_terdata": len(ada),
             "piotroski_rinci": [None if x is None else bool(x) for x in syarat], "beneish": None}

    if not keuangan:
        try:
            ar0, ar1 = v(bs, AR, 0), v(bs, AR, 1)
            cogs0, cogs1 = v(inc, COGS, 0), v(inc, COGS, 1)
            if gm0 is None and cogs0 is not None and rev0:
                gm0 = (rev0 - cogs0) / rev0
            if gm1 is None and cogs1 is not None and rev1:
                gm1 = (rev1 - cogs1) / rev1
            ca0, ca1 = v(bs, CA, 0), v(bs, CA, 1)
            ppe0, ppe1 = v(bs, PPE, 0), v(bs, PPE, 1)
            sec0, sec1 = v(bs, SEC, 0) or 0.0, v(bs, SEC, 1) or 0.0
            dep0, dep1 = v(cf, DEP, 0) or v(inc, DEP, 0), v(cf, DEP, 1) or v(inc, DEP, 1)
            sga0, sga1 = v(inc, SGA, 0), v(inc, SGA, 1)
            cl0, cl1 = v(bs, CL, 0), v(bs, CL, 1)
            ltd0, ltd1 = v(bs, LTD, 0) or 0.0, v(bs, LTD, 1) or 0.0
            dsri = (ar0 / rev0) / (ar1 / rev1)
            gmi = gm1 / gm0
            aqi = (1 - (ca0 + ppe0 + sec0) / ta0) / (1 - (ca1 + ppe1 + sec1) / ta1)
            sgi = rev0 / rev1
            depi = (dep1 / (dep1 + ppe1)) / (dep0 / (dep0 + ppe0))
            sgai = (sga0 / rev0) / (sga1 / rev1) if sga0 and sga1 else 1.0
            tata = (ni0 - cfo0) / ta0
            lvgi = ((cl0 + ltd0) / ta0) / ((cl1 + ltd1) / ta1)
            m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
                 - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
            hasil["beneish"] = round(m, 2) if math.isfinite(m) else None
        except (TypeError, ZeroDivisionError):
            hasil["beneish"] = None
    return hasil


def persen(x):
    """yfinance kadang memberi 0,028 dan kadang 2,8 untuk 2,8%."""
    x = angka(x)
    if x is None:
        return None
    return round(x * 100, 2) if abs(x) < 1.5 else round(x, 2)


KURS = {}


def kurs(mata_uang: str | None) -> float:
    """Kurs ke Rupiah untuk emiten yang melapor dalam mata uang asing (mis. USD)."""
    if not mata_uang or mata_uang == "IDR":
        return 1.0
    if mata_uang not in KURS:
        import yfinance as yf

        try:
            KURS[mata_uang] = float(yf.Ticker(f"{mata_uang}IDR=X").history(period="5d")["Close"].iloc[-1])
        except Exception as e:  # noqa: BLE001
            print(f"  ! kurs {mata_uang}: {e}")
            KURS[mata_uang] = float("nan")
    return KURS[mata_uang]


def kali(lap: dict, k: float, kecuali=("Laba per saham",)) -> dict:
    if k == 1.0 or not lap.get("data"):
        return lap
    for n, v in lap["data"].items():
        if n not in kecuali:
            lap["data"][n] = [None if x is None else round(x * k) for x in v]
    return lap


# Saringan kualitas gaya Yahoo Screener (materi Stock School) dan pengaman dasar.
SYARAT_KUALITAS = [
    ("ROE > 10%", "roe", lambda v: v > 10),
    ("ROA > 5%", "roa", lambda v: v > 5),
    ("Margin laba > 5%", "margin_laba", lambda v: v > 5),
    ("Rasio lancar > 1", "rasio_lancar", lambda v: v > 1),
    ("Rasio cepat > 1", "rasio_cepat", lambda v: v > 1),
    ("Arus kas operasi positif", "arus_kas_operasi", lambda v: v > 0),
    ("PEG < 1", "peg", lambda v: 0 < v < 1),
]


def periksa(d: dict) -> dict:
    hasil = []
    for nama, k, uji in SYARAT_KUALITAS:
        v = d.get(k)
        hasil.append(None if v is None else bool(uji(v)))
    terdata = [x for x in hasil if x is not None]
    bahaya = []
    if (d.get("eps") is not None and d["eps"] < 0) or (d.get("margin_laba") is not None and d["margin_laba"] < 0):
        bahaya.append("rugi bersih")
    if d.get("arus_kas_operasi") is not None and d["arus_kas_operasi"] < 0:
        bahaya.append("arus kas operasi negatif")
    if d.get("piotroski") is not None and (d.get("piotroski_terdata") or 0) >= 7 and d["piotroski"] <= 2:
        bahaya.append(f"Piotroski F-Score rendah ({d['piotroski']}/{d['piotroski_terdata']})")
    peringatan = []
    if d.get("beneish") is not None and d["beneish"] > -1.78:
        peringatan.append(f"Beneish M-Score {d['beneish']:.2f}".replace('.', ',') + " (> -1,78: pola laporan keuangan perlu dicermati)")
    return {
        "kualitas": sum(terdata),            # jumlah syarat terpenuhi
        "kualitas_terdata": len(terdata),    # jumlah syarat yang datanya ada (bank tak punya rasio lancar/cepat)
        "lolos_kualitas": all(x is not False for x in hasil) and len(terdata) >= 5,
        "bahaya": bahaya,
        "peringatan": peringatan,
    }


def ambil_satu(kode: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(f"{kode}.JK")
    info = t.info or {}
    mu = info.get("financialCurrency") or "IDR"
    k = kurs(mu)
    harga = angka(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))
    nilai_buku = angka(info.get("bookValue"), 2)
    if nilai_buku is not None and math.isfinite(k):
        nilai_buku = round(nilai_buku * k, 2)
    pbv = round(harga / nilai_buku, 2) if harga and nilai_buku and nilai_buku > 0 else None
    per_maju = angka(info.get("forwardPE"), 2)
    if per_maju is not None and (per_maju <= 0 or per_maju > 300):
        per_maju = None
    ringkas = {
        "kode": kode,
        "nama": info.get("longName") or info.get("shortName") or kode,
        "sektor": SEKTOR.get(info.get("sector"), info.get("sector") or "Lainnya"),
        "industri": info.get("industry"),
        "kapitalisasi": angka(info.get("marketCap"), 0),
        "per": angka(info.get("trailingPE"), 2),
        "per_maju": per_maju,
        "pbv": pbv,
        "roe": persen(info.get("returnOnEquity")),
        "roa": persen(info.get("returnOnAssets")),
        "der": angka((info.get("debtToEquity") or 0) / 100, 2) if info.get("debtToEquity") is not None else None,
        "margin_laba": persen(info.get("profitMargins")),
        "tumbuh_pendapatan": persen(info.get("revenueGrowth")),
        "tumbuh_laba": persen(info.get("earningsGrowth")),
        "imbal_dividen": persen(info.get("dividendYield")),
        "eps": angka(info.get("trailingEps"), 2),
        "nilai_buku": nilai_buku,
        "mata_uang_laporan": mu,
        "beta": angka(info.get("beta"), 2),
        "tertinggi_52m": angka(info.get("fiftyTwoWeekHigh"), 0),
        "terendah_52m": angka(info.get("fiftyTwoWeekLow"), 0),
        "jumlah_saham": angka(info.get("sharesOutstanding"), 0),
        "rasio_lancar": angka(info.get("currentRatio"), 2),
        "rasio_cepat": angka(info.get("quickRatio"), 2),
        "arus_kas_operasi": (round(info["operatingCashflow"] * k) if info.get("operatingCashflow") is not None
                             and math.isfinite(k) else None),
        "peg": angka(info.get("trailingPegRatio") or info.get("pegRatio"), 2),
        "situs": info.get("website"),
    }
    detail = dict(ringkas)
    detail["profil"] = info.get("longBusinessSummary")
    detail["diperbarui"] = datetime.now(WIB).strftime("%Y-%m-%d")
    detail["kurs_konversi"] = None if k == 1.0 else round(k, 2)
    try:  # skor Piotroski & Beneish (rasio, jadi tidak perlu konversi kurs)
        sk = hitung_skor(t.income_stmt, t.balance_sheet, t.cashflow, keuangan=ringkas.get("sektor") == "Keuangan")
        ringkas.update(sk)
        detail.update(sk)
    except Exception as e:  # noqa: BLE001
        print(f"  ! {kode} skor Piotroski/Beneish: {e}")
    for nama, fungsi, n in [
        ("laba_rugi_tahunan", lambda: t.income_stmt, 4),
        ("laba_rugi_kuartal", lambda: t.quarterly_income_stmt, 6),
    ]:
        try:
            detail[nama] = kali(baris_laporan(fungsi(), LAPORAN_LABA, n), k if math.isfinite(k) else 1.0)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {kode} {nama}: {e}")
    for nama, fungsi, baris in [
        ("neraca_tahunan", lambda: t.balance_sheet, NERACA),
        ("arus_kas_tahunan", lambda: t.cashflow, ARUS_KAS),
    ]:
        try:
            detail[nama] = kali(baris_laporan(fungsi(), baris, 4), k if math.isfinite(k) else 1.0)
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


KUNCI_RINGKAS = None


def main():
    (FOLDER / "fundamental").mkdir(parents=True, exist_ok=True)
    kode_list = cfg.kode_semesta()
    hari_ini = datetime.now(WIB).date()

    def umur(kode):
        f = FOLDER / "fundamental" / f"{kode}.json"
        if not f.exists():
            return 10_000
        try:
            t = json.loads(f.read_text()).get("diperbarui")
            return (hari_ini - datetime.strptime(t, "%Y-%m-%d").date()).days if t else 9_999
        except Exception:  # noqa: BLE001
            return 10_000

    umur_map = {k: umur(k) for k in kode_list}
    # berkas lama belum punya rasio baru (lancar, cepat, arus kas, PEG): anggap kedaluwarsa
    for k in kode_list:
        f = FOLDER / "fundamental" / f"{k}.json"
        if umur_map[k] < 10_000 and f.exists() and '"piotroski"' not in f.read_text():
            umur_map[k] = 9_000
    kosong = sum(1 for v in umur_map.values() if v >= 10_000)
    lama_format = sum(1 for v in umur_map.values() if v == 9_000)
    batas = len(kode_list) if (kosong + lama_format) > len(kode_list) // 2 else MAKS_PER_JALAN
    perlu = sorted([k for k in kode_list if umur_map[k] >= UMUR_MAKS_HARI], key=lambda k: -umur_map[k])[:batas]
    print(f"Fundamental: {len(perlu)} dari {len(kode_list)} saham diperbarui hari ini.")

    gagal = []
    for kode in perlu:
        for coba in range(2):
            try:
                _, detail = ambil_satu(kode)
                (FOLDER / "fundamental" / f"{kode}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, separators=(",", ":")))
                break
            except Exception as e:  # noqa: BLE001
                print(f"  ! {kode} percobaan {coba + 1}: {e}")
                time.sleep(5)
        else:
            gagal.append(kode)
        time.sleep(0.7)

    kunci = ["kode", "nama", "sektor", "industri", "kapitalisasi", "per", "per_maju", "pbv", "roe", "roa", "der",
             "margin_laba", "tumbuh_pendapatan", "tumbuh_laba", "imbal_dividen", "eps", "nilai_buku", "mata_uang_laporan",
             "beta", "tertinggi_52m", "terendah_52m", "jumlah_saham", "situs", "diperbarui",
             "rasio_lancar", "rasio_cepat", "arus_kas_operasi", "peg",
             "piotroski", "piotroski_terdata", "piotroski_rinci", "beneish"]
    semua = []
    for kode in kode_list:
        f = FOLDER / "fundamental" / f"{kode}.json"
        if f.exists():
            d = {k: json.loads(f.read_text()).get(k) for k in kunci}
            d.update(periksa(d))
            semua.append(d)
    (FOLDER / "fundamental.json").write_text(json.dumps(
        {"dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "saham": semua},
        ensure_ascii=False, separators=(",", ":")))
    print(f"Fundamental: {len(semua)} saham tersedia, {len(gagal)} gagal {gagal[:15]}")


if __name__ == "__main__":
    main()
