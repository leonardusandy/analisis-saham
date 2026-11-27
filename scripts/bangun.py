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


def hari_bursa_terakhir(kini):
    """Tanggal hari bursa terakhir yang sudah tutup (data Yahoo biasanya tersedia ±16.30 WIB)."""
    from datetime import timedelta
    import json
    libur = set(json.loads((Path(__file__).parent / "data" / "libur_bursa.json").read_text())["tanggal"])
    bukan = lambda d: d.weekday() >= 5 or d.isoformat() in libur  # noqa: E731
    t = kini.date()
    if bukan(t) or (kini.hour * 60 + kini.minute) < 16 * 60 + 30:
        t -= timedelta(days=1)
    while bukan(t):
        t -= timedelta(days=1)
    return t.isoformat()


def perlu_susulan(k: Path) -> bool:
    """Jadwal GitHub bisa terlewat. Bila data harga tertinggal, jalankan mode harian
    dari pemicu apa pun (berita, laptop), paling sering sekali per 3 jam."""
    import json
    from datetime import datetime, timedelta, timezone
    kini = datetime.now(timezone(timedelta(hours=7)))
    try:
        tgl = json.loads((k / "ringkasan.json").read_text())["tanggal_data"]
    except Exception:  # noqa: BLE001
        return False
    if tgl >= hari_bursa_terakhir(kini):
        return False
    p = k / "status_susulan.json"
    try:
        akhir = datetime.fromisoformat(json.loads(p.read_text())["percobaan"])
        if kini - akhir < timedelta(hours=3):
            return False
    except Exception:  # noqa: BLE001
        pass
    p.write_text(json.dumps({"percobaan": kini.isoformat(), "data": tgl}))
    return True


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "harian"
    k = cfg.KELUAR
    k.mkdir(parents=True, exist_ok=True)
    ada = lambda f: (k / f).exists()  # noqa: E731
    print(f"Mode: {mode}; folder terbitan: {k}")
    if mode != "harian" and perlu_susulan(k):
        mode = "harian"
        print("Data harga tertinggal dari hari bursa terakhir: dijalankan sebagai mode harian (susulan).")

    jalan("semesta", wajib=True)
    jalan("lapkeu")  # laporan keuangan unggahan pengguna (hanya berubah bila ada kiriman mode lapkeu)
    if mode == "harian" or not ada("ringkasan.json"):
        jalan("jalankan", wajib=True)
    if mode == "harian" or not ada("fundamental.json"):
        jalan("fundamental")
    if mode == "harian" or not ada("strategi.json"):
        jalan("strategi")
    if mode == "harian" or not ada("stockpick.json"):
        jalan("stockpick")
    if mode == "harian" or not ada("model.json"):
        jalan("model")
    if mode in ("harian", "posisi") or not ada("prediksi.json"):
        jalan("prediksi")
    if mode == "harian" or not ada("kepemilikan.json"):
        jalan("kepemilikan")
    if mode in ("harian", "berita") or not ada("global.json"):
        jalan("global_pasar")
    if mode in ("harian", "berita") or not ada("berita.json"):
        jalan("berita")
    jalan("olah_broker")


if __name__ == "__main__":
    main()
