"""Pengaturan analisis. Ubah nilai di sini sesuai kebutuhan Anda."""
import json
import os
from pathlib import Path

AKAR_REPO = Path(__file__).resolve().parent.parent
# Folder hasil olahan. Di GitHub Actions diarahkan ke folder situs yang diterbitkan (tidak disimpan di repo).
KELUAR = Path(os.environ.get("DATA_KELUAR", AKAR_REPO / "docs" / "data"))
# Kiriman harian dari laptop (disimpan di repo)
HARI_BROKER = AKAR_REPO / "docs" / "data" / "broker" / "hari"

# Cakupan analisis: lapis 1 (kapitalisasi >= Rp10 T), lapis 2 (Rp1–10 T), dan saham grup konglomerat
# (scripts/data/konglo.json). Daftar lengkapnya disusun otomatis oleh semesta.py.
BATAS_LAPIS1 = 10e12
BATAS_LAPIS2 = 1e12

# Konstituen LQ45 periode 2 November 2026 – 29 Januari 2027.
# BEI mengevaluasi ulang daftar ini setiap Februari, Mei, Agustus, dan November.
# Perbarui daftar ini saat ada perubahan.
SAHAM = [
    "AADI", "ADMR", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ASII", "BBCA",
    "BBNI", "BBRI", "BBTN", "BMRI", "BRPT", "BUMI", "CPIN", "CUAN", "DEWA",
    "EMTK", "ESSA", "EXCL", "GOTO", "HRTA", "ICBP", "INCO", "INDF", "INDY",
    "INKP", "ISAT", "ITMG", "JPFA", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC",
    "NCKL", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "WIFI",
]

KODE_IHSG = "^JKSE"

# Jumlah hari data historis yang diambil
PERIODE = "2y"

# Biaya transaksi (sesuaikan dengan sekuritas Anda)
BIAYA_BELI = 0.0015   # 0,15%
BIAYA_JUAL = 0.0025   # 0,25% (termasuk PPh final 0,1%)

# Level transaksi berbasis ATR (Average True Range, 14 hari)
KALI_ATR_STOP = 1.0     # batas rugi = harga masuk - 1,0 x ATR
KALI_ATR_TARGET = 1.5   # target    = harga masuk + 1,5 x ATR

# Kandidat minimal memiliki skor ini
SKOR_MINIMAL = 5

# Nilai transaksi rata-rata 20 hari minimal (Rupiah) agar dianggap likuid
NILAI_TRANSAKSI_MINIMAL = 1_000_000_000  # Rp1 miliar

# Uji balik: berapa hari maksimal posisi dipegang
HARI_PEGANG_MAKS = 3


def semesta() -> list[dict]:
    """Daftar saham yang dianalisis (dari semesta.json); bila belum ada, LQ45."""
    p = KELUAR / "semesta.json"
    if p.exists():
        return json.loads(p.read_text())["saham"]
    return [{"kode": k, "lapis": 1, "grup": None, "likuid": True, "lq45": True} for k in SAHAM]


def kode_semesta() -> list[str]:
    return [s["kode"] for s in semesta()]

# Strategi utama (aturan J, hasil uji 3 tahun): pegang maksimal 3 hari, batas rugi -5% dari harga beli.
STOP_PERSEN = 0.05
KALI_ATR_TARGET_ACUAN = 2.0  # target acuan saja; aturan keluar utama = jual penutupan hari ke-3
