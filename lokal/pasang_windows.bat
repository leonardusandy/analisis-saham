@echo off
setlocal
title Pemasang Pengumpul Data Saham
cd /d "%~dp0"
echo ==========================================================
echo   PEMASANG PENGUMPUL DATA BROKER ^& ASING (sekali saja)
echo ==========================================================
echo.

rem --- 1. Cari Python ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [!] Python belum terpasang.
  echo     Unduh dari https://www.python.org/downloads/ lalu pasang.
  echo     PENTING: centang "Add python.exe to PATH" saat memasang.
  echo     Setelah itu jalankan berkas ini lagi.
  pause
  exit /b 1
)
echo [1/4] Python ditemukan:
%PY% --version

rem --- 2. Pasang pustaka ---
echo.
echo [2/4] Memasang pustaka (requests, curl_cffi)...
%PY% -m pip install --user --quiet --upgrade -r requirements-lokal.txt
if errorlevel 1 (
  echo [!] Gagal memasang pustaka. Periksa koneksi internet lalu coba lagi.
  pause
  exit /b 1
)
%PY% kumpul_lokal.py --uji
if errorlevel 1 ( pause & exit /b 1 )

rem --- 3. Token GitHub ---
echo.
echo [3/4] Token GitHub
if exist "%USERPROFILE%\.analisis-saham-token.txt" (
  echo     Token sudah tersimpan. Tekan Enter untuk memakai yang lama,
  echo     atau tempel token baru lalu Enter.
) else (
  echo     Tempel token GitHub Anda ^(klik kanan untuk menempel^), lalu Enter.
)
set "TOKEN="
set /p "TOKEN=    Token: "
if defined TOKEN (
  > "%USERPROFILE%\.analisis-saham-token.txt" echo %TOKEN%
  echo     Token disimpan di %USERPROFILE%\.analisis-saham-token.txt
)
if not exist "%USERPROFILE%\.analisis-saham-token.txt" (
  echo [!] Token belum ada. Jalankan pemasang ini lagi setelah membuat token.
  pause
  exit /b 1
)

rem --- 4. Jadwal otomatis ---
echo.
echo [4/4] Membuat jadwal otomatis setiap hari pukul 17.45,
echo       diulang tiap jam sampai 22.45 bila laptop baru menyala.
> "%~dp0jalankan_windows.bat" (
  echo @echo off
  echo cd /d "%~dp0"
  echo %PY% kumpul_lokal.py ^>^> "%~dp0log.txt" 2^>^&1
)
schtasks /Create /TN "AnalisisSahamHarian" /TR "\"%~dp0jalankan_windows.bat\"" /SC DAILY /ST 17:45 /RI 60 /DU 05:00 /F >nul
if errorlevel 1 (
  echo [!] Gagal membuat jadwal. Coba klik kanan berkas ini lalu "Run as administrator".
) else (
  echo     Jadwal "AnalisisSahamHarian" dibuat.
)

echo.
echo ==========================================================
echo  Sekarang mengambil data pertama kali (20 hari bursa terakhir).
echo  Ini bisa makan waktu 10-15 menit. Jangan tutup jendela ini.
echo ==========================================================
%PY% kumpul_lokal.py
echo.
echo Selesai. Mulai sekarang data diambil otomatis setiap sore.
echo Catatan kegiatan tersimpan di: %~dp0log.txt
pause
