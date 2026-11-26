"""Bangun seluruh data web ke folder terbitan (DATA_KELUAR), sesuai mode.

  harian  : semua bagian (dijalankan sore hari setelah bursa tutup)
  berita  : hanya berita (tiap 2 jam)
  broker  : hanya olah kiriman laptop (saat laptop mengirim data / tampilan berubah)

Bagian yang belum pernah ada di folder terbitan selalu dibangun, apa pun modenya.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

SKRIP = Path(__file__).parent


def jalan(nama: str, *args: str, wajib: bool = False) -> None:
    print(f"\n=== {nama} {' '.join(args)} ===", flush=True)
    r = subprocess.run([sys.executable, str(SKRIP / f"{nama}.py"), *args])
    if r.returncode != 0:
        print(f"!!! {nama} gagal (kode {r.returncode})", flush=True)
        if wajib:
            sys.exit(r.returncode)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "harian"
    k = cfg.KELUAR
    k.mkdir(parents=True, exist_ok=True)
    ada = lambda f: (k / f).exists()  # noqa: E731
    print(f"Mode: {mode}; folder terbitan: {k}")

    jalan("semesta", wajib=True)
    if mode == "harian" or not ada("ringkasan.json"):
        jalan("jalankan", wajib=True)
    if mode == "harian" or not ada("fundamental.json"):
        jalan("fundamental")
    if mode == "harian" or not ada("kepemilikan.json"):
        jalan("kepemilikan")
    if mode in ("harian", "berita") or not ada("berita.json"):
        jalan("berita")
    jalan("olah_broker")


if __name__ == "__main__":
    main()
