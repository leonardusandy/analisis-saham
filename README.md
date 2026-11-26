# Analisis Saham Harian LQ45

Web analisis teknikal saham LQ45 yang diperbarui otomatis setiap hari bursa sekitar pukul 17.30 WIB.

**Alamat web:** https://leonardusandy.github.io/analisis-saham/

## Isi web

- **Ringkasan**: IHSG, kondisi pasar, saham naik dan turun terbesar, hasil uji balik strategi
- **Kandidat Besok**: saham dengan skor tertinggi, lengkap dengan harga masuk, target, batas rugi, dan jumlah lot yang disarankan
- **Semua Saham**: tabel 45 saham yang bisa diurutkan
- **Grafik**: grafik lilin, MA20/MA50, pita Bollinger, volume, RSI, MACD
- **Jurnal Transaksi**: catat transaksi Anda dan lihat hasil bersih setelah biaya
- **Panduan**: cara skor dihitung dan aturan pengelolaan risiko

## Cara kerja

1. GitHub Actions (`.github/workflows/harian.yml`) berjalan Senin–Jumat pukul 17.30 WIB.
2. Skrip `scripts/jalankan.py` mengambil data harian dari Yahoo Finance, lalu menghitung indikator, skor, level transaksi, dan uji balik 2 tahun.
3. Hasilnya disimpan di `docs/data/` dan ditampilkan oleh `docs/index.html` lewat GitHub Pages.

## Mengubah pengaturan

Semua pengaturan ada di `scripts/config.py`:

- `SAHAM`: daftar kode saham (perbarui setiap ada evaluasi LQ45)
- `BIAYA_BELI`, `BIAYA_JUAL`: biaya transaksi sekuritas Anda
- `KALI_ATR_STOP`, `KALI_ATR_TARGET`: jarak batas rugi dan target
- `SKOR_MINIMAL`: syarat skor untuk menjadi kandidat

Untuk mengedit: buka berkasnya di GitHub, klik ikon pensil, ubah nilainya, lalu klik **Commit changes**.

## Menjalankan manual

Tab **Actions** → **Analisis harian** → **Run workflow**.

## Catatan

Data dari Yahoo Finance tidak resmi dan bisa terlambat atau tidak lengkap. Web ini alat bantu analisis, bukan nasihat investasi.
