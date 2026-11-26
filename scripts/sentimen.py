"""Analisis judul berita: saham terkait, sentimen, dan dampak.

Dua cara:
  1. Aturan kata kunci (selalu berjalan, gratis).
  2. AI Claude (bila rahasia ANTHROPIC_API_KEY tersedia): saham terkait, sentimen per saham,
     dan satu kalimat dampak. Hanya judul yang dikirim, bukan isi berita.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

# ---------------------------------------------------------------------------
# Tema -> saham terkait (dikaitkan bila judul menyebut tema, bukan nama emiten)
# ---------------------------------------------------------------------------
TEMA = {
    r"\btelko\b|telekomunikasi|operator seluler|menara telekomunikasi": "TLKM ISAT EXCL MTEL TOWR TBIG",
    r"batu ?bara|\bcoal\b": "PTBA ITMG ADRO AADI BUMI INDY HRUM BYAN DEWA GEMS",
    r"\bnikel\b": "NCKL INCO MBMA ANTM MDKA HRUM",
    r"\bemas\b|\bgold\b": "ANTM MDKA HRTA BRMS ARCI AMMN",
    r"tembaga": "AMMN MDKA",
    r"\bcpo\b|sawit|minyak kelapa": "AALI LSIP SIMP SSMS TAPG DSNG SMAR",
    r"harga minyak|\bmigas\b|minyak mentah": "MEDC ENRG PGAS AKRA ELSA",
    r"\bproperti\b|perumahan": "BSDE CTRA PWON SMRA PANI",
    r"perbankan|\bbank\b|suku bunga|bi rate|\bkredit\b": "BBCA BBRI BMRI BBNI BBTN BRIS",
    r"\bsemen\b": "SMGR INTP",
    r"rokok|cukai": "GGRM HMSP WIIM",
    r"\bcukai\b|tembakau": "GGRM HMSP WIIM",
    r"otomotif|mobil listrik|kendaraan": "ASII AUTO IMAS",
    r"ritel|daya beli|konsumsi rumah tangga": "AMRT MAPI ACES MIDI ERAA",
    r"\bkonstruksi\b|infrastruktur": "PTPP WIKA ADHI WSKT",
    r"baterai|\bev\b": "MBMA NCKL INCO ANTM",
    r"teknologi|startup|digital": "GOTO BUKA EMTK DCII",
    r"data ?center|pusat data": "DCII EMTK TLKM",
    r"unggas|ayam|pakan": "CPIN JPFA MAIN",
    r"geotermal|panas bumi|energi baru": "PGEO BREN",
    r"petrokimia": "TPIA BRPT",
}
POLA_TEMA = [(re.compile(p, re.I), k.split()) for p, k in TEMA.items()]

# ---------------------------------------------------------------------------
# Kata kunci sentimen (huruf kecil). Frasa dicek sebelum kata tunggal.
# ---------------------------------------------------------------------------
POSITIF = [
    "laba naik", "laba melonjak", "laba tumbuh", "laba bersih naik", "kinerja moncer", "cetak rekor", "rekor tertinggi",
    "net buy", "beli bersih", "diborong", "diburu", "akumulasi", "rekomendasi beli", "target harga naik",
    "naik", "menguat", "melonjak", "melesat", "melejit", "terbang", "meroket", "rebound", "pulih", "tumbuh",
    "untung", "cuan", "dividen", "buyback", "kontrak baru", "raih kontrak", "ekspansi", "akuisisi", "upgrade",
    "ara", "bullish", "positif", "optimis", "optimisme", "rekor", "moncer", "diuntungkan", "berbalik naik",
]
NEGATIF = [
    "laba turun", "laba anjlok", "laba merosot", "rugi bersih", "gagal bayar", "net sell", "jual bersih",
    "dana asing keluar", "terancam keluar", "aksi jual", "dilepas", "ambil untung", "profit taking",
    "turun", "melemah", "anjlok", "merosot", "ambles", "ambruk", "longsor", "terkoreksi", "koreksi", "rugi",
    "tertekan", "terancam", "dihantui", "dibayangi", "badai", "babak belur", "pkpu", "pailit", "suspensi",
    "disuspensi", "denda", "gugatan", "sanksi", "downgrade", "arb", "bearish", "negatif", "pesimis", "lesu",
    "mengkhawatirkan", "waspada", "jatuh", "terjun", "boncos",
]


def _pola(kata):
    urut = sorted(kata, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in urut) + r")\b", re.I)


P_POS, P_NEG = _pola(POSITIF), _pola(NEGATIF)


def sentimen_aturan(judul: str) -> dict:
    teks = judul.lower()
    pos = [m.group(1).lower() for m in P_POS.finditer(teks)]
    neg = [m.group(1).lower() for m in P_NEG.finditer(teks)]
    # "naik" di dalam "laba naik" tidak dihitung dua kali karena frasa panjang dicocokkan lebih dulu
    skor = len(pos) - len(neg)
    label = "positif" if skor > 0 else "negatif" if skor < 0 else "netral"
    if pos and neg and abs(skor) <= 1 and len(pos) + len(neg) >= 3:
        label = "campuran"
    return {"label": label, "skor": skor, "kata": sorted(set(pos + neg))}


def tema_terkait(judul: str, semesta: set[str], sudah: list[str]) -> list[str]:
    hasil = []
    for pola, kode in POLA_TEMA:
        if pola.search(judul):
            hasil += [k for k in kode if k in semesta and k not in sudah and k not in hasil]
    return hasil[:8]


# ---------------------------------------------------------------------------
# AI (opsional)
# ---------------------------------------------------------------------------
MODEL = os.environ.get("MODEL_BERITA", "claude-haiku-5-5")
PROMPT = """Anda analis pasar saham Indonesia. Untuk setiap judul berita di bawah, tentukan saham BEI yang
terdampak langsung (maksimal 5, kode 4 huruf), sentimen bagi tiap saham (positif, negatif, atau netral),
dan satu kalimat singkat (maksimal 18 kata, bahasa Indonesia) tentang dampaknya bagi saham itu.
Gunakan hanya yang bisa disimpulkan dari judul. Jika judul tidak berkaitan dengan saham tertentu
(misalnya berita makro umum), berikan daftar kosong. Jangan mengarang angka.

Jawab HANYA dengan JSON: [{{"i": nomor, "saham": [{{"kode": "XXXX", "sentimen": "positif", "dampak": "..."}}]}}]

Judul:
{daftar}"""


def analisis_ai(items: list[dict], semua_kode: set[str]) -> int:
    """Isi item['analisis'] untuk item yang belum punya. Mengembalikan jumlah judul yang dianalisis."""
    kunci = os.environ.get("ANTHROPIC_API_KEY")
    if not kunci:
        return 0
    import requests

    perlu = [b for b in items if "analisis" not in b]
    selesai = 0
    for i in range(0, len(perlu), 25):
        kelompok = perlu[i:i + 25]
        daftar = "\n".join(f"{n}. {b['judul']}" for n, b in enumerate(kelompok))
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": kunci, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": MODEL, "max_tokens": 4000,
                      "messages": [{"role": "user", "content": PROMPT.format(daftar=daftar)}]},
                timeout=120,
            )
            r.raise_for_status()
            teks = "".join(c.get("text", "") for c in r.json().get("content", []))
            data = json.loads(teks[teks.index("["): teks.rindex("]") + 1])
        except Exception as e:  # noqa: BLE001
            print(f"  ! analisis AI gagal: {str(e)[:200]}")
            break
        for d in data:
            try:
                b = kelompok[int(d["i"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            b["analisis"] = [
                {"kode": s["kode"].upper(), "sentimen": s.get("sentimen", "netral"), "dampak": (s.get("dampak") or "")[:160]}
                for s in d.get("saham", [])
                if isinstance(s, dict) and str(s.get("kode", "")).upper() in semua_kode
                and s.get("sentimen") in ("positif", "negatif", "netral")
            ][:5]
            b["oleh"] = "AI"
            selesai += 1
        time.sleep(1)
    return selesai


def semua_kode_bei() -> set[str]:
    """Kode saham yang dikenal (semesta + seluruh kode dari kapitalisasi awal)."""
    p = Path(__file__).parent / "data" / "kapitalisasi_awal.json"
    kode = set(cfg.kode_semesta())
    if p.exists():
        kode |= set(json.loads(p.read_text())["kapitalisasi"])
    return kode
