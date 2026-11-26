# Panduan Pengumpul Data di Laptop

Situs Indo Premier dan IDX menolak server GitHub, jadi data broker dan transaksi asing
diambil dari laptop Anda lalu dikirim ke GitHub. Pemasangan cukup sekali.

## Langkah 1 — Buat token GitHub (5 menit)

Token ini semacam kata sandi khusus yang hanya boleh menulis ke repositori `analisis-saham`.

1. Buka https://github.com/settings/personal-access-tokens/new
2. **Token name**: `laptop-analisis-saham`
3. **Expiration**: pilih **Custom** lalu 1 tahun ke depan (atau 90 hari jika ingin lebih aman)
4. **Repository access**: pilih **Only select repositories**, lalu pilih `leonardusandy/analisis-saham`
5. **Permissions** → **Repository permissions** → **Contents**: ubah menjadi **Read and write**
6. Klik **Generate token** di bawah, lalu klik ikon salin. Token diawali `github_pat_…`
   (token hanya ditampilkan sekali; jika hilang, buat baru)

Jangan bagikan token ini ke siapa pun.

## Langkah 2 — Pasang Python (jika belum ada)

- **Windows**: unduh dari https://www.python.org/downloads/ , jalankan pemasangnya, dan
  **centang "Add python.exe to PATH"** di layar pertama.
- **Mac**: unduh dari alamat yang sama.

## Langkah 3 — Jalankan pemasang

1. Ekstrak berkas zip `pengumpul-laptop.zip` ke folder tetap, misalnya `Dokumen\analisis-saham-laptop`
   (jangan di folder Unduhan yang sering dibersihkan; jangan dipindah setelah dipasang).
2. **Windows**: klik dua kali `pasang_windows.bat`.
   **Mac**: buka Terminal, ketik `bash ` lalu seret berkas `pasang_mac.sh` ke Terminal, tekan Enter.
3. Tempel token saat diminta (Windows: klik kanan untuk menempel), tekan Enter.
4. Pemasang langsung mengambil data hingga 60 hari bursa terakhir (beberapa menit). Biarkan sampai selesai.

Setelah itu laptop mengambil data otomatis setiap hari pukul 17.45 dan mencoba lagi
setiap jam sampai 22.45 jika laptop baru dinyalakan. Jika laptop mati beberapa hari, data
yang terlewat (hingga 60 hari bursa untuk data IDX, 20 hari untuk broker) diambil sekaligus saat skrip berjalan berikutnya.

## Tentang jendela Chrome yang muncul sendiri

Situs IDX memasang verifikasi "Anda manusia" (Cloudflare). Program membuka jendela Chrome
khusus (terpisah dari Chrome biasa Anda, profilnya di folder `.analisis-saham-chrome`) lalu
mengambil data dari dalam halaman IDX.

- Jika di jendela itu muncul **kotak verifikasi**, klik kotaknya. Program menunggu sampai 4 menit.
- Setelah lolos sekali, biasanya verifikasi tidak diminta lagi selama beberapa waktu.
- Saat jadwal otomatis berjalan dan Anda tidak di depan laptop, verifikasi yang tidak diklik
  membuat data IDX hari itu terlewat; program mencoba lagi tiap jam sampai 22.45, dan
  hari yang terlewat diambil pada percobaan berikutnya yang berhasil.
- Jangan menutup jendela Chrome itu saat program berjalan; ia tertutup sendiri setelah selesai.

## Memeriksa apakah berjalan

- Catatan kegiatan ada di `log.txt` di folder yang sama.
- Di GitHub: tab **Actions** → alur kerja **Olah data broker** muncul setiap kali laptop mengirim data.
- Di web: menu **Aliran Dana** menampilkan tanggal data terakhir.

## Menjalankan manual

- Windows: klik dua kali `jalankan_windows.bat`
- Mac: `python3 kumpul_lokal.py` di folder ini

## Menghapus

- Windows: buka Command Prompt, ketik `schtasks /Delete /TN AnalisisSahamHarian /F`
- Mac: `crontab -e` lalu hapus baris yang berisi `kumpul_lokal.py`
- Hapus berkas token: `.analisis-saham-token.txt` di folder pengguna Anda, dan cabut tokennya di
  https://github.com/settings/personal-access-tokens

## Tentang data

- **Ringkasan broker** (10 pembeli dan 10 penjual terbesar per saham, diurutkan menurut lot) dan
  **nilai bersih asing** dari halaman publik Indo Premier. Angka ≥ 1 juta dibulatkan satu desimal.
- **Transaksi asing seluruh saham** dari situs IDX, bila situs itu tidak memblokir koneksi Anda.
- Pengambilan dilakukan pelan (±0,4 detik antarsaham) agar tidak membebani situs sumber.
  Gunakan untuk keperluan pribadi.
