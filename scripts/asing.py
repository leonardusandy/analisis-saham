"""Ambil Ringkasan Saham harian dari situs IDX: transaksi asing, nilai, frekuensi.

Situs IDX kadang memblokir akses otomatis. Jika gagal, skrip berhenti tanpa
merusak data lama dan web tetap berjalan tanpa data asing.
Hasil: docs/data/asing.json
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

BERKAS = Path(__file__).resolve().parent.parent / "docs" / "data" / "asing.json"
WIB = timezone(timedelta(hours=7))
URL = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0&date={}"
HARI_SIMPAN = 60


def sesi():
    from curl_cffi import requests as creq

    s = creq.Session(impersonate="chrome")
    s.headers.update({"Referer": "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/"})
    try:
        s.get("https://www.idx.co.id/id", timeout=30)
    except Exception:  # noqa: BLE001
        pass
    return s


def ambil_tanggal(s, tgl: datetime):
    r = s.get(URL.format(tgl.strftime("%Y%m%d")), timeout=40)
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")
    data = r.json().get("data") or []
    return data


def ringkas_hari(data: list[dict]) -> tuple[dict, dict]:
    per_saham, pasar = {}, {}
    baris = []
    for d in data:
        kode = d.get("StockCode")
        close = float(d.get("Close") or 0)
        prev = float(d.get("Previous") or 0)
        fb = float(d.get("ForeignBuy") or 0)
        fs = float(d.get("ForeignSell") or 0)
        nilai = float(d.get("Value") or 0)
        baris.append({
            "kode": kode, "nama": d.get("StockName"), "tutup": close,
            "ubah_pct": round((close - prev) / prev * 100, 2) if prev else 0,
            "nilai": nilai, "frek": int(d.get("Frequency") or 0),
            "asing_bersih": round((fb - fs) * close),
        })
        if kode in cfg.SAHAM:
            per_saham[kode] = [fb, fs, close, nilai, int(d.get("Frequency") or 0)]
    aktif = [b for b in baris if b["nilai"] > 0]
    pasar["naik"] = sum(b["ubah_pct"] > 0 for b in aktif)
    pasar["turun"] = sum(b["ubah_pct"] < 0 for b in aktif)
    pasar["tetap"] = sum(b["ubah_pct"] == 0 for b in aktif)
    pasar["nilai_total"] = round(sum(b["nilai"] for b in aktif))
    pasar["asing_bersih_total"] = round(sum(b["asing_bersih"] for b in aktif))
    pasar["teratas_nilai"] = sorted(aktif, key=lambda b: b["nilai"], reverse=True)[:10]
    pasar["asing_beli"] = sorted(aktif, key=lambda b: b["asing_bersih"], reverse=True)[:10]
    pasar["asing_jual"] = sorted(aktif, key=lambda b: b["asing_bersih"])[:10]
    return per_saham, pasar


def main():
    data = {"harian": {}, "pasar": None, "tanggal_terakhir": None}
    if BERKAS.exists():
        try:
            data = json.loads(BERKAS.read_text())
        except Exception:  # noqa: BLE001
            pass

    try:
        s = sesi()
    except Exception as e:  # noqa: BLE001
        print("Tidak bisa membuat sesi:", e)
        return

    hari_ini = datetime.now(WIB).replace(hour=0, minute=0, second=0, microsecond=0)
    # Isi riwayat sampai 60 hari ke belakang bila masih kosong, selain itu cukup 7 hari terakhir
    mundur = 90 if len(data["harian"]) < 10 else 7
    berhasil = 0
    for i in range(mundur, -1, -1):
        tgl = hari_ini - timedelta(days=i)
        if tgl.weekday() >= 5:
            continue
        kunci = tgl.strftime("%Y-%m-%d")
        if kunci in data["harian"] and i > 0:
            continue
        try:
            isi = ambil_tanggal(s, tgl)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {kunci}: {e}")
            if berhasil == 0 and i == mundur:
                pass
            time.sleep(2)
            continue
        if not isi:
            continue  # hari libur
        per_saham, pasar = ringkas_hari(isi)
        data["harian"][kunci] = per_saham
        if data["tanggal_terakhir"] is None or kunci >= data["tanggal_terakhir"]:
            data["tanggal_terakhir"] = kunci
            data["pasar"] = pasar
        berhasil += 1
        time.sleep(1.5)

    if berhasil == 0:
        print("Data IDX tidak dapat diambil hari ini (kemungkinan diblokir). Data lama dipertahankan.")
        return

    simpan = sorted(data["harian"])[-HARI_SIMPAN:]
    data["harian"] = {k: data["harian"][k] for k in simpan}
    data["kolom"] = ["asing_beli_lembar", "asing_jual_lembar", "tutup", "nilai", "frekuensi"]
    data["dibuat"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")
    BERKAS.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"Asing: {berhasil} hari diperbarui, terakhir {data['tanggal_terakhir']}.")


if __name__ == "__main__":
    main()
