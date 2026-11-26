"""Salin situs ke folder terbit lalu enkripsi semua berkas data dengan sandi web.

Pemakaian: python scripts/enkripsi.py _site _terbit
Sandi diambil dari variabel lingkungan SANDI_WEB (rahasia repositori GitHub).
Tanpa SANDI_WEB, situs disalin apa adanya (tanpa kunci).

Format tiap berkas: 12 bita IV + sandi AES-256-GCM dari JSON yang dimampatkan gzip.
Kunci = PBKDF2-SHA256(sandi, garam, ITERASI). Halaman web menurunkan kunci yang sama
di peramban (WebCrypto) setelah pengguna memasukkan sandi.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERASI = 310_000
GARAM = hashlib.sha256(b"analisis-saham/garam-v1").digest()[:16]
# Dibiarkan terbuka karena dibaca pengumpul di laptop; isinya hanya daftar kode saham dan tanggal.
TERBUKA = {"semesta.json", "broker/indeks.json"}


def bungkus(aes: AESGCM, isi: bytes) -> bytes:
    iv = os.urandom(12)
    return iv + aes.encrypt(iv, gzip.compress(isi, mtime=0), None)


def buka(data: bytes, sandi: str):
    """Kebalikan bungkus(): dipakai untuk memulihkan riwayat dari situs."""
    kunci = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=GARAM, iterations=ITERASI).derive(sandi.encode())
    return json.loads(gzip.decompress(AESGCM(kunci).decrypt(data[:12], data[12:], None)))


def main(asal: str, tujuan: str) -> None:
    asal_p, tujuan_p = Path(asal), Path(tujuan)
    if tujuan_p.exists():
        shutil.rmtree(tujuan_p)
    shutil.copytree(asal_p, tujuan_p)
    sandi = os.environ.get("SANDI_WEB", "")
    if not sandi:
        print("SANDI_WEB belum diisi: situs diterbitkan TANPA kunci.")
        return
    kunci = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=GARAM, iterations=ITERASI).derive(sandi.encode())
    aes = AESGCM(kunci)
    data = tujuan_p / "data"
    n = 0
    for p in sorted(data.rglob("*.json")):
        rel = p.relative_to(data).as_posix()
        if rel in TERBUKA:
            continue
        p.write_bytes(bungkus(aes, p.read_bytes()))
        n += 1
    (data / "kunci.json").write_text(json.dumps({
        "v": 1, "garam": base64.b64encode(GARAM).decode(), "iterasi": ITERASI,
        "uji": base64.b64encode(bungkus(aes, b'"ok"')).decode(),
    }))
    print(f"Data terkunci: {n} berkas dienkripsi, {len(TERBUKA)} dibiarkan terbuka.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
