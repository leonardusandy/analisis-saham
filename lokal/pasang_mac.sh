#!/bin/bash
# Pemasang pengumpul data broker & asing untuk Mac (sekali saja).
# Jalankan di Terminal:  bash pasang_mac.sh
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "=== Pemasang pengumpul data saham ==="
if ! command -v python3 >/dev/null; then
  echo "[!] Python 3 belum ada. Pasang dari https://www.python.org/downloads/ lalu jalankan lagi."
  exit 1
fi
PY="$(command -v python3)"
echo "[1/4] Python: $($PY --version)"
echo "[2/4] Memasang pustaka…"
$PY -m pip install --user --quiet --upgrade -r requirements-lokal.txt || { echo "[!] Gagal memasang pustaka"; exit 1; }
$PY kumpul_lokal.py --uji || exit 1
echo "[3/4] Tempel token GitHub Anda lalu Enter (kosongkan untuk memakai token lama):"
read -r -s TOKEN
if [ -n "$TOKEN" ]; then echo "$TOKEN" > "$HOME/.analisis-saham-token.txt"; chmod 600 "$HOME/.analisis-saham-token.txt"; fi
[ -f "$HOME/.analisis-saham-token.txt" ] || { echo "[!] Token belum ada."; exit 1; }
echo "[4/4] Membuat jadwal: setiap jam 17.45–22.45 (zona waktu Mac Anda harus WIB)."
BARIS="45 17-22 * * * cd \"$DIR\" && \"$PY\" kumpul_lokal.py >> \"$DIR/log.txt\" 2>&1"
( crontab -l 2>/dev/null | grep -v "kumpul_lokal.py"; echo "$BARIS" ) | crontab -
echo "Jadwal dibuat. Mengambil data pertama kali (10–15 menit)…"
$PY kumpul_lokal.py
echo "Selesai."
