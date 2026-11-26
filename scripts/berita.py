"""Kumpulkan judul berita pasar saham dari RSS portal berita dan Google News.

Hanya judul, sumber, waktu, dan tautan yang disimpan; isi berita dibaca di situs aslinya.
Hasil: docs/data/berita.json
"""
from __future__ import annotations

import calendar
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

BERKAS = Path(__file__).resolve().parent.parent / "docs" / "data" / "berita.json"
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
POLA = {
    k: re.compile(r"\b(" + "|".join(re.escape(x) for x in [k] + ALIAS.get(k, [])) + r")\b")
    for k in cfg.SAHAM
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


def gabung(baru: list[dict], lama: list[dict], batas: int) -> list[dict]:
    batas_waktu = (datetime.now(WIB) - timedelta(days=UMUR_MAKS_HARI)).strftime("%Y-%m-%dT%H:%M:%S")
    terlihat, hasil = set(), []
    for b in sorted(baru + lama, key=lambda x: x["waktu"], reverse=True):
        kunci = re.sub(r"\W+", "", b["judul"].lower())[:80]
        if kunci in terlihat or b["waktu"] < batas_waktu:
            continue
        terlihat.add(kunci)
        hasil.append(b)
    return hasil[:batas]


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
    for kode in cfg.SAHAM:
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

    data = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "pasar": gabung(pasar, lama.get("pasar", []), 120),
        "per_saham": {
            k: gabung(per_saham.get(k, []), lama.get("per_saham", {}).get(k, []), 25) for k in cfg.SAHAM
        },
    }
    BERKAS.parent.mkdir(parents=True, exist_ok=True)
    BERKAS.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    n = sum(len(v) for v in data["per_saham"].values())
    print(f"Selesai: {len(data['pasar'])} berita pasar, {n} berita per saham.")


if __name__ == "__main__":
    main()
