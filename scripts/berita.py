"""Kumpulkan judul berita pasar saham dari RSS portal berita dan Google News.

Hanya judul, sumber, waktu, dan tautan yang disimpan; isi berita dibaca di situs aslinya.
Hasil: docs/data/berita.json
"""
from __future__ import annotations

import calendar
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
import sentimen as snt  # noqa: E402

BERKAS = cfg.KELUAR / "berita.json"
WIB = timezone(timedelta(hours=7))
UMUR_MAKS_HARI = 14
AGEN = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

GN = "https://news.google.com/rss/search?hl=id&gl=ID&ceid=ID:id&q="

SUMBER_PASAR = [
    ("CNBC Indonesia", "https://www.cnbcindonesia.com/market/rss"),
    ("Antara", "https://www.antaranews.com/rss/ekonomi-bursa.xml"),
    ("Investortrust", "https://investortrust.id/rss/market.rss"),
    ("Google News", GN + quote_plus(
        "(IHSG OR saham OR emiten OR bursa) when:2d (site:kontan.co.id OR site:bisnis.com OR "
        "site:idxchannel.com OR site:emitennews.com OR site:investor.id OR site:katadata.co.id OR "
        "site:cnbcindonesia.com OR site:idnfinancials.com)")),
    # aksi korporasi: dividen, RUPS, laporan keuangan, right issue, buyback, stock split
    ("Google News", GN + quote_plus(
        '(dividen OR "cum date" OR RUPS OR "laporan keuangan" OR "right issue" OR HMETD OR buyback OR "stock split") '
        '(saham OR emiten OR Tbk) when:3d')),
]

# Nama lain yang sering dipakai media untuk emiten LQ45
ALIAS = {
    "BBCA": ["BCA", "Bank Central Asia"], "BBRI": ["BRI", "Bank Rakyat Indonesia"],
    "BMRI": ["Bank Mandiri"], "BBNI": ["BNI", "Bank Negara Indonesia"], "BBTN": ["BTN"],
    "TLKM": ["Telkom"], "ASII": ["Astra International"], "UNVR": ["Unilever Indonesia"],
    "ISAT": ["Indosat"], "EXCL": ["XLSmart", "XL Axiata"], "ANTM": ["Antam", "Aneka Tambang"],
    "PTBA": ["Bukit Asam"], "UNTR": ["United Tractors"], "INDF": ["Indofood Sukses"],
    "ICBP": ["Indofood CBP"], "KLBF": ["Kalbe"], "ADRO": ["Adaro Energy", "AlamTri Resources"],
    "AADI": ["Adaro Andalan"], "ADMR": ["Adaro Minerals", "AlamTri Minerals"],
    "AMMN": ["Amman Mineral"], "INCO": ["Vale Indonesia"], "MDKA": ["Merdeka Copper"],
    "MBMA": ["Merdeka Battery"], "MEDC": ["Medco"], "PGAS": ["PGN", "Perusahaan Gas Negara"],
    "PGEO": ["Pertamina Geothermal"], "GOTO": ["GoTo"], "AMRT": ["Alfamart", "Sumber Alfaria"],
    "SMGR": ["Semen Indonesia", "SIG"], "CPIN": ["Charoen Pokphand"], "JPFA": ["Japfa"],
    "BRPT": ["Barito Pacific"], "CUAN": ["Petrindo"], "BUMI": ["Bumi Resources"],
    "DEWA": ["Darma Henwa"], "EMTK": ["Emtek", "Elang Mahkota"], "INDY": ["Indika Energy"],
    "INKP": ["Indah Kiat"], "ITMG": ["Indo Tambangraya"], "HRTA": ["Hartadinata"],
    "MAPI": ["Mitra Adiperkasa"], "NCKL": ["Trimegah Bangun", "Harita Nickel"],
    "AKRA": ["AKR Corporindo"], "ESSA": ["ESSA Industries"], "WIFI": ["Solusi Sinergi Digital"],
}
SEMESTA = cfg.kode_semesta()


def _nama_pendek(nama: str) -> str | None:
    """'PT Bank Central Asia Tbk' -> 'Bank Central Asia'. Hanya nama >= 2 kata agar tidak salah cocok."""
    n = re.sub(r"\(.*?\)|\bPT\b|\bTbk\.?|\bPersero\b|,", " ", nama or "", flags=re.I)
    n = re.sub(r"\s+", " ", n).strip()
    return n if len(n.split()) >= 2 and len(n) >= 8 else None


try:
    for _s in json.loads((cfg.KELUAR / "fundamental.json").read_text())["saham"]:
        _n = _nama_pendek(_s.get("nama"))
        if _n and _s["kode"] in SEMESTA:
            ALIAS.setdefault(_s["kode"], [])
            if _n not in ALIAS[_s["kode"]]:
                ALIAS[_s["kode"]].append(_n)
except Exception:  # noqa: BLE001
    pass
# Kode saham dicocokkan persis huruf besar (mis. "BBCA"); nama lain hanya untuk emiten yang dikenal
POLA = {
    k: re.compile(r"\b(" + "|".join(re.escape(x) for x in [k] + ALIAS.get(k, [])) + r")\b")
    for k in sorted(set(SEMESTA) | set(cfg.SAHAM))
}


def tandai(judul: str) -> list[str]:
    return [k for k, p in POLA.items() if p.search(judul)]


def bersihkan_judul(judul: str, sumber: str) -> tuple[str, str]:
    """Google News menulis 'Judul - Nama Media'. Pisahkan nama medianya."""
    if sumber == "Google News" and " - " in judul:
        j, s = judul.rsplit(" - ", 1)
        return j.strip(), s.strip()
    return judul.strip(), sumber


def baca_rss(sumber: str, url: str) -> list[dict]:
    f = None
    for coba in range(3):
        try:
            f = feedparser.parse(url, agent=AGEN)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {sumber}: {e}")
            return []
        if getattr(f, "status", 200) != 429:
            break
        time.sleep(10 * (coba + 1))
    hasil = []
    for e in f.entries[:60]:
        judul = (e.get("title") or "").strip()
        tautan = e.get("link")
        if not judul or not tautan:
            continue
        waktu_struct = e.get("published_parsed") or e.get("updated_parsed")
        if waktu_struct:
            waktu = datetime.fromtimestamp(calendar.timegm(waktu_struct), tz=WIB)
        else:
            waktu = datetime.now(WIB)
        judul, nama_media = bersihkan_judul(judul, sumber)
        if len(judul) < 20:
            continue
        hasil.append(
            {
                "judul": judul,
                "tautan": tautan,
                "sumber": nama_media,
                "waktu": waktu.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
                "kode": tandai(judul),
            }
        )
    status = getattr(f, "status", "?")
    print(f"  {sumber}: {len(hasil)} berita (status {status})")
    return hasil


def kunci_judul(b: dict) -> str:
    return re.sub(r"\W+", "", b["judul"].lower())[:80]


def gabung(baru: list[dict], lama: list[dict], batas: int) -> list[dict]:
    batas_waktu = (datetime.now(WIB) - timedelta(days=UMUR_MAKS_HARI)).strftime("%Y-%m-%dT%H:%M:%S")
    analisis_lama = {kunci_judul(b): b for b in lama if "analisis" in b}
    terlihat, hasil = set(), []
    for b in sorted(baru + lama, key=lambda x: x["waktu"], reverse=True):
        kunci = kunci_judul(b)
        if kunci in terlihat or b["waktu"] < batas_waktu:
            continue
        terlihat.add(kunci)
        if "analisis" not in b and kunci in analisis_lama:
            b["analisis"] = analisis_lama[kunci]["analisis"]
            b["oleh"] = analisis_lama[kunci].get("oleh")
        hasil.append(b)
    return hasil[:batas]


# Media yang dianggap terpercaya untuk keputusan trading: media bisnis/ekonomi arus utama, kantor berita,
# dan situs resmi. Berita dari sumber lain tetap ditampilkan, tetapi tidak dipakai untuk menunda pembelian.
TERPERCAYA = re.compile(
    r"kontan|bisnis\.com|bisnis indonesia|cnbc|idx ?channel|idxchannel|investor\.id|investor daily|katadata|emiten ?news|"
    r"idn ?financials|antara|reuters|bloomberg|kompas|tempo|detik|investortrust|jakarta post|jakarta globe|"
    r"liputan6|kumparan|idx\.co\.id|bursa efek|ojk", re.I)


def lengkapi(b: dict) -> dict:
    """Saham terkait lewat tema dan sentimen kata kunci untuk satu berita."""
    b["terpercaya"] = bool(TERPERCAYA.search(b.get("sumber") or ""))
    b["kode"] = sorted(set(b.get("kode", [])) | set(tandai(b["judul"])))
    b["sentimen"] = snt.sentimen_aturan(b["judul"])
    # saham terkait tema hanya bila beritanya bersentimen jelas, agar berita umum tidak penuh label
    b["terkait"] = (snt.tema_terkait(b["judul"], set(SEMESTA), b["kode"])
                    if b["sentimen"]["label"] in ("positif", "negatif") else [])
    return b


def main():
    lama = {"pasar": [], "per_saham": {}}
    if BERKAS.exists():
        try:
            lama = json.loads(BERKAS.read_text())
        except Exception:  # noqa: BLE001
            pass

    print("Berita pasar:")
    pasar = []
    for sumber, url in SUMBER_PASAR:
        pasar += baca_rss(sumber, url)
        time.sleep(1)

    print("Berita per saham:")
    per_saham = {}
    # Pencarian bergilir: tiap pembaruan ±55 saham, berurutan dari yang paling ramai/besar,
    # sehingga semua saham dalam cakupan tercari kira-kira sekali sehari (8 pembaruan/hari).
    try:
        sm = json.loads((cfg.KELUAR / "semesta.json").read_text())["saham"]
        urutan = [x["kode"] for x in sorted(sm, key=lambda x: (not x.get("lq45"), not x.get("likuid"), -(x.get("kap") or 0)))]
    except Exception:  # noqa: BLE001
        urutan = list(cfg.SAHAM)
    berkas_giliran = cfg.KELUAR / "berita_giliran.json"
    try:
        mulai = json.loads(berkas_giliran.read_text())["mulai"] % max(1, len(urutan))
    except Exception:  # noqa: BLE001
        mulai = 0
    PER_JALAN = 55
    giliran = [urutan[(mulai + i) % len(urutan)] for i in range(min(PER_JALAN, len(urutan)))]
    berkas_giliran.write_text(json.dumps({"mulai": (mulai + len(giliran)) % max(1, len(urutan))}))
    print(f"  giliran saham {mulai + 1}–{mulai + len(giliran)} dari {len(urutan)}")
    for kode in giliran:
        q = f'"{kode}" saham when:7d'
        hasil = baca_rss("Google News", GN + quote_plus(q))
        for h in hasil:
            if kode not in h["kode"]:
                h["kode"] = [kode] + h["kode"]
        per_saham[kode] = hasil
        time.sleep(2)

    # Berita pasar yang menyebut kode saham juga masuk ke daftar saham itu
    for b in pasar:
        for k in b["kode"]:
            per_saham.setdefault(k, []).append(b)

    # Lengkapi saham terkait & sentimen; analisis AI bila kunci tersedia (hanya judul baru)
    pasar_akhir = gabung(pasar, lama.get("pasar", []), 120)
    per_saham_akhir = {
        k: v for k in sorted(set(per_saham) | set(lama.get("per_saham", {})))
        if (v := gabung(per_saham.get(k, []), lama.get("per_saham", {}).get(k, []), 25))
    }
    semua = {kunci_judul(b): b for b in pasar_akhir}
    for v in per_saham_akhir.values():
        for b in v:
            semua.setdefault(kunci_judul(b), b)
    for b in semua.values():
        lengkapi(b)
    n_ai = snt.analisis_ai(list(semua.values()), snt.semua_kode_bei())
    if n_ai:
        print(f"Analisis AI: {n_ai} judul baru.")
    # salin hasil AI ke salinan judul yang sama di daftar lain
    for daftar in [pasar_akhir, *per_saham_akhir.values()]:
        for b in daftar:
            s = semua.get(kunci_judul(b))
            if s is not b and s and "analisis" in s:
                b["analisis"], b["oleh"] = s["analisis"], s.get("oleh")

    data = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "ai": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "pasar": pasar_akhir,
        "per_saham": per_saham_akhir,
    }
    BERKAS.parent.mkdir(parents=True, exist_ok=True)
    BERKAS.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    n = sum(len(v) for v in data["per_saham"].values())
    print(f"Selesai: {len(data['pasar'])} berita pasar, {n} berita per saham.")


if __name__ == "__main__":
    main()
