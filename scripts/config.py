"""Pengaturan analisis. Ubah nilai di sini sesuai kebutuhan Anda."""

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
NILAI_TRANSAKSI_MINIMAL = 10_000_000_000  # Rp10 miliar

# Uji balik: berapa hari maksimal posisi dipegang
HARI_PEGANG_MAKS = 3
