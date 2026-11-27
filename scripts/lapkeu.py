"""Laporan keuangan yang diunggah pengguna di halaman "Laporan Keuangan Saya".

Halaman web membaca file Excel IDX di perangkat pengguna, menghitung ringkasan rasio, lalu mengirim
ringkasan itu terenkripsi (sandi web) lewat input workflow `posisi` dengan mode `lapkeu`.
Skrip ini membuka kiriman, memeriksa isinya, dan menggabungkannya ke <DATA_KELUAR>/lapkeu.json
(maks 8 periode per saham). Tanpa kiriman, berkas lama dibiarkan (dibuat kosong bila belum ada).
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

WIB = timezone(timedelta(hours=7))
RASIO = ("roe", "roa", "laba_tumbuh", "pend_tumbuh", "margin_kotor", "margin_kotor_lalu", "margin_bersih", "der", "der_lalu",
         "cr", "cr_lalu", "laba", "laba_lalu", "cfo")
PUTUSAN = ("kuat", "sedang", "waspada", "lemah", "tidak terbaca")


def bersihkan(x: dict) -> dict | None:
    kode = str(x.get("kode", "")).upper()
    periode = str(x.get("periode", ""))[:16]
    if not re.fullmatch(r"[A-Z]{4}", kode) or not re.fullmatch(r"\d{4}-(TAHUNAN|Q[1-4])", periode):
        return None
    angka = lambda v: float(v) if isinstance(v, (int, float)) and abs(v) < 1e16 else None  # noqa: E731
    r = x.get("rasio") or {}
    syarat = [[str(s[0])[:60], s[1] if isinstance(s[1], bool) else None] for s in (x.get("syarat") or [])[:10]
              if isinstance(s, list) and len(s) == 2]
    return {
        "kode": kode, "periode": periode, "periode_teks": str(x.get("periode_teks", ""))[:60],
        "akhir": str(x.get("akhir", ""))[:10], "bulan": int(x.get("bulan") or 12), "bank": bool(x.get("bank")),
        "putusan": x.get("putusan") if x.get("putusan") in PUTUSAN else "tidak terbaca",
        "rasio": {k: angka(r.get(k)) for k in RASIO}, "syarat": syarat,
        "skor": sum(1 for s in syarat if s[1]), "terdata": sum(1 for s in syarat if s[1] is not None),
        "terbaca": int(x.get("terbaca") or 0), "berkas": str(x.get("berkas", ""))[:120],
        "diunggah": str(x.get("diunggah", ""))[:16], "nama": str(x.get("nama", ""))[:80],
    }


def main():
    p = cfg.KELUAR / "lapkeu.json"
    data = {"saham": {}}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    kiriman = os.environ.get("POSISI_TERKUNCI", "").strip()
    sandi = os.environ.get("SANDI_WEB", "")
    if kiriman and sandi:
        try:
            from enkripsi import buka
            isi = buka(base64.b64decode(kiriman), sandi)
        except Exception as e:  # noqa: BLE001
            print("  ! kiriman tidak bisa dibuka:", e)
            isi = {}
        baru = [y for y in (bersihkan(x) for x in (isi.get("lapkeu") or [])[:30]) if y]
        for y in baru:
            lst = [z for z in data["saham"].get(y["kode"], []) if z["periode"] != y["periode"]] + [y]
            data["saham"][y["kode"]] = sorted(lst, key=lambda z: z["akhir"], reverse=True)[:8]
        hapus = [str(h) for h in (isi.get("hapus_lapkeu") or [])[:30]]
        for h in hapus:
            k, _, per = h.partition("|")
            if k in data["saham"]:
                data["saham"][k] = [z for z in data["saham"][k] if z["periode"] != per]
                if not data["saham"][k]:
                    del data["saham"][k]
        if baru or hapus:
            print(f"Laporan keuangan unggahan: {len(baru)} diterima, {len(hapus)} dihapus.")
    data["dibuat"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")
    p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"Laporan keuangan unggahan tersimpan: {len(data['saham'])} saham.")


if __name__ == "__main__":
    main()
