"""Jejak prediksi: simpan analisis & rekomendasi tiap hari, lalu nilai hasilnya setelah bursa tutup.

Dijalankan pada mode harian (17.30 WIB, setelah bursa tutup):
  1. Menilai catatan hari-hari sebelumnya dengan harga terbaru.
  2. Menambah catatan baru dari analisis hari ini.
  3. Menghitung statistik (keseluruhan dan per ciri) sebagai bahan menyusun model yang lebih baik.

Jenis catatan:
  beli : setiap saham ramai dengan sinyal aturan J (ditandai jika masuk Kandidat/Analisa harian).
         Dinilai dengan aturan yang sama dengan uji: beli di pembukaan besok, batas rugi -5%,
         jual di penutupan hari ke-3. Dicatat juga apakah R1/R2/CL tersentuh dalam 3 hari.
  tren : saham di tabel uptrend/sideways dan yang keluar tabel. Dinilai 5 hari bursa kemudian:
         uptrend benar jika harga naik; sideways benar jika bergerak <= 5%; keluar tabel benar
         jika harga turun.

Riwayat lengkap: <DATA_KELUAR>/prediksi/riwayat.json (disimpan di cache Actions). Jika cache hilang,
riwayat dipulihkan dari salinan terenkripsi di situs (memakai SANDI_WEB).
Ringkasan untuk web: <DATA_KELUAR>/prediksi.json
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

WIB = timezone(timedelta(hours=7))
SITUS = os.environ.get("SITUS_WEB", "https://leonardusandy.github.io/analisis-saham/")
HARI_BELI, HARI_TREN = 3, 5


def baca(p: Path, bawaan=None):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return bawaan


def pulihkan_dari_situs():
    """Ambil salinan riwayat yang sudah terbit (terenkripsi) bila cache kosong."""
    try:
        import requests
        r = requests.get(SITUS + "data/prediksi/riwayat.json", timeout=30)
        if r.status_code != 200:
            return None
        sandi = os.environ.get("SANDI_WEB", "")
        if not sandi:
            return r.json()
        from enkripsi import buka
        return buka(r.content, sandi)
    except Exception as e:  # noqa: BLE001
        print("  ! riwayat tidak bisa dipulihkan dari situs:", e)
        return None


def lilin(kode: str, simpan: dict):
    if kode not in simpan:
        d = baca(cfg.KELUAR / "saham" / f"{kode}.json")
        simpan[kode] = d["lilin"] if d else None
    return simpan[kode]


def nilai_beli(c: dict, L: list) -> None:
    tgl = [x["t"] for x in L]
    if c["tanggal"] not in tgl:
        return
    i = tgl.index(c["tanggal"])
    ke = L[i + 1:i + 1 + HARI_BELI]
    if not ke:
        c["status"] = "menunggu"
        return
    beli = ke[0]["o"]
    if not beli:
        return
    stop = beli * (1 - cfg.STOP_PERSEN)
    r = c.get("rencana") or {}
    keluar, cara = None, None
    for n, x in enumerate(ke):
        if n > 0 and x["o"] <= stop:
            keluar, cara = x["o"], "batas rugi (buka di bawah)"
            break
        if x["l"] <= stop:
            keluar, cara = stop, "batas rugi"
            break
    selesai = keluar is not None or len(ke) >= HARI_BELI
    if keluar is None:
        keluar, cara = ke[-1]["c"], ("jual hari ke-3" if selesai else f"berjalan hari ke-{len(ke)}")
    hasil = (keluar * (1 - cfg.BIAYA_JUAL)) / (beli * (1 + cfg.BIAYA_BELI)) - 1
    tinggi = max(x["h"] for x in ke)
    c["hasil"] = {
        "beli": beli, "keluar": round(keluar, 1), "cara": cara, "pct": round(hasil * 100, 2),
        "naik_maks_pct": round((tinggi / beli - 1) * 100, 2),
        "sesuai_entry": bool(r.get("entry") and beli <= r["entry"][1] * 1.005),
        "kena_r1": bool(r.get("r1") and tinggi >= r["r1"]),
        "kena_r2": bool(r.get("r2") and tinggi >= r["r2"]),
        "kena_cl": cara.startswith("batas rugi"),
        "sampai": ke[-1]["t"],
    }
    c["status"] = "selesai" if selesai else "berjalan"
    if selesai:
        c["benar"] = hasil > 0


def nilai_tren(c: dict, L: list) -> None:
    tgl = [x["t"] for x in L]
    if c["tanggal"] not in tgl:
        return
    i = tgl.index(c["tanggal"])
    ke = L[i + 1:i + 1 + HARI_TREN]
    if not ke:
        c["status"] = "menunggu"
        return
    awal = L[i]["c"]
    ubah = (ke[-1]["c"] / awal - 1) * 100
    c["hasil"] = {"pct": round(ubah, 2), "hari": len(ke), "sampai": ke[-1]["t"]}
    if len(ke) < HARI_TREN:
        c["status"] = "berjalan"
        return
    c["status"] = "selesai"
    p = c["prediksi"]
    c["benar"] = ubah > 0 if p == "up" else abs(ubah) <= 5 if p == "side" else ubah < 0


def nilai_model(c: dict, L: list) -> None:
    tgl = [x["t"] for x in L]
    if c["tanggal"] not in tgl:
        return
    i = tgl.index(c["tanggal"])
    ke = L[i + 1:i + 1 + HARI_BELI]
    if not ke:
        return
    ubah = (ke[-1]["c"] / L[i]["c"] - 1) * 100
    c["hasil"] = {"pct": round(ubah, 2), "hari": len(ke)}
    if len(ke) >= HARI_BELI:
        c["status"] = "selesai"
        c["benar"] = (c["p"] >= 50) == (ubah > 0)
    else:
        c["status"] = "berjalan"


def catat_model(md: dict) -> list[dict]:
    if not md:
        return []
    t = md["tanggal"]
    return [{"id": f"{t}|{x['kode']}|model", "jenis": "model", "tanggal": t, "kode": x["kode"], "status": "menunggu",
             "p": x["p"], "keyakinan": x["keyakinan"]} for x in md["prediksi"]]


def catat_hari_ini(rk: dict, sp: dict, fund: dict) -> list[dict]:
    t = rk["tanggal_data"]
    ihsg_naik = bool(rk.get("pasar_mendukung"))
    pilih_analisa = {a["kode"]: a for a in (sp or {}).get("analisa", [])}
    kandidat = set(rk.get("kandidat", [])) | set(rk.get("kandidat_tunda", []))
    baris_sp = {b["kode"]: b for b in (sp or {}).get("uptrend", []) + (sp or {}).get("sideways", [])}
    arah_sektor = {x["nama"]: x["arah"] for x in (sp or {}).get("sektor", [])}
    baru = []
    for s in rk["saham"]:
        if s.get("tanggal") != t or not s.get("likuid") or not s.get("sinyal_j"):
            continue
        k = s["kode"]
        f, b = fund.get(k, {}), baris_sp.get(k, {})
        a = pilih_analisa.get(k)
        lv = s.get("level") or {}
        rencana = ({"entry": a["entry"], "r1": a["r1"], "r2": a["r2"], "cl": a["cl"]} if a else
                   {"entry": [lv.get("masuk"), lv.get("masuk")], "r1": lv.get("target"), "r2": None, "cl": lv.get("stop")})
        sektor = f.get("sektor") or "Lainnya"
        baru.append({
            "id": f"{t}|{k}|beli", "jenis": "beli", "tanggal": t, "kode": k, "status": "menunggu",
            "dipilih": [x for x, ya in (("analisa", k in pilih_analisa), ("kandidat", k in kandidat)) if ya],
            "rencana": rencana, "tutup": s.get("tutup"),
            "fitur": {
                "ihsg_naik": ihsg_naik, "macd": bool(s.get("sinyal_macd")), "kualitas": bool(f.get("lolos_kualitas")),
                "bahaya": bool(f.get("bahaya")), "sektor": sektor, "sektor_arah": arah_sektor.get(sektor, "netral"),
                "lapis": s.get("lapis"), "lq45": bool(s.get("lq45")), "rsi": s.get("rsi"), "rasio_vol": s.get("rasio_vol"),
                "skor": s.get("skor"), "tingkat": b.get("tingkat"), "kuat": b.get("kuat"), "murah": b.get("murah"),
                "ubah_hari": s.get("perubahan_pct"), "ubah_20h": s.get("ubah_20h"), "nilai_miliar": s.get("nilai_rata20_miliar"),
            },
        })
    for b in (sp or {}).get("uptrend", []) + (sp or {}).get("sideways", []):
        baru.append({"id": f"{t}|{b['kode']}|tren", "jenis": "tren", "tanggal": t, "kode": b["kode"], "status": "menunggu",
                     "prediksi": b["status"], "fitur": {"tingkat": b.get("tingkat"), "warna": b.get("warna"),
                                                        "kuat": b.get("kuat"), "sektor": b.get("sektor")}})
    for x in (sp or {}).get("keluar", []):
        baru.append({"id": f"{t}|{x['kode']}|keluar", "jenis": "tren", "tanggal": t, "kode": x["kode"], "status": "menunggu",
                     "prediksi": "keluar", "fitur": {"dari": x["dari"], "ke": x["ke"]}})
    return baru


def ringkas(arr: list[dict]) -> dict | None:
    r = [c["hasil"]["pct"] for c in arr if c.get("status") == "selesai" and c.get("hasil")]
    if not r:
        return None
    m, k = [x for x in r if x > 0], [x for x in r if x <= 0]
    return {"n": len(r), "menang": round(len(m) / len(r) * 100, 1), "rata": round(sum(r) / len(r), 2),
            "pf": round(sum(m) / -sum(k), 2) if k and sum(k) else None,
            "rata_menang": round(sum(m) / len(m), 2) if m else 0, "rata_kalah": round(sum(k) / len(k), 2) if k else 0}


def statistik(cat: list[dict]) -> dict:
    beli = [c for c in cat if c["jenis"] == "beli"]
    pilih = [c for c in beli if c.get("dipilih")]
    tren = [c for c in cat if c["jenis"] == "tren"]
    ciri = {
        "Pasar (IHSG > MA20)": lambda c: "ya" if c["fitur"]["ihsg_naik"] else "tidak",
        "MACD baru potong ke atas": lambda c: "ya" if c["fitur"]["macd"] else "tidak",
        "Lolos saringan kualitas": lambda c: "ya" if c["fitur"]["kualitas"] else "tidak",
        "Arah sektor": lambda c: c["fitur"]["sektor_arah"],
        "Lapis": lambda c: f"lapis {c['fitur']['lapis'] or '–'}",
        "Volume (× rata-rata)": lambda c: ("< 1,5×" if (c["fitur"]["rasio_vol"] or 0) < 1.5
                                         else "1,5–3×" if c["fitur"]["rasio_vol"] < 3 else "≥ 3×"),
        "RSI": lambda c: "< 60" if (c["fitur"]["rsi"] or 0) < 60 else "60–70" if c["fitur"]["rsi"] < 70 else "≥ 70",
        "Masuk sesuai rentang entry": lambda c: "ya" if (c.get("hasil") or {}).get("sesuai_entry") else "tidak",
    }
    per_ciri = {}
    for nama, fn in ciri.items():
        grup = defaultdict(list)
        for c in beli:
            grup[fn(c)].append(c)
        per_ciri[nama] = {g: ringkas(v) for g, v in sorted(grup.items())}
    akurasi_tren = {}
    for p, label in (("up", "Uptrend → naik dalam 5 hari"), ("side", "Sideways → bergerak ≤ 5%"),
                     ("keluar", "Keluar tabel → turun dalam 5 hari")):
        sel = [c for c in tren if c["prediksi"] == p and c.get("status") == "selesai"]
        akurasi_tren[label] = {"n": len(sel), "benar": round(sum(c["benar"] for c in sel) / len(sel) * 100, 1) if sel else None,
                               "rata": round(sum(c["hasil"]["pct"] for c in sel) / len(sel), 2) if sel else None}
    # kurva hasil: rata-rata transaksi pilihan per tanggal sinyal, dijumlahkan
    per_tgl = defaultdict(list)
    for c in pilih:
        if c.get("status") == "selesai":
            per_tgl[c["tanggal"]].append(c["hasil"]["pct"])
    kurva, total = [], 0.0
    for t in sorted(per_tgl):
        total += sum(per_tgl[t]) / len(per_tgl[t])
        kurva.append({"t": t, "v": round(total, 2)})
    r1 = [c for c in pilih if c.get("status") == "selesai"]
    mdl = [c for c in cat if c["jenis"] == "model" and c.get("status") == "selesai"]

    def akurasi(arr):
        return {"n": len(arr), "benar": round(sum(c["benar"] for c in arr) / len(arr) * 100, 1) if arr else None}
    per_hari = defaultdict(list)
    for c in mdl:
        per_hari[c["tanggal"]].append(c)
    model = {
        "semua": akurasi(mdl),
        "per_keyakinan": {y: akurasi([c for c in mdl if c["keyakinan"] == y]) for y in ("tinggi", "sedang", "rendah")},
        "per_arah": {"naik": akurasi([c for c in mdl if c["p"] >= 50]), "turun": akurasi([c for c in mdl if c["p"] < 50])},
        "harian": [{"t": t, **akurasi(v)} for t, v in sorted(per_hari.items())][-120:],
    }
    return {
        "beli_semua": ringkas(beli), "beli_dipilih": ringkas(pilih),
        "beli_analisa": ringkas([c for c in beli if "analisa" in c.get("dipilih", [])]),
        "kena": {"r1": round(sum(c["hasil"]["kena_r1"] for c in r1) / len(r1) * 100, 1) if r1 else None,
                 "r2": round(sum(c["hasil"]["kena_r2"] for c in r1) / len(r1) * 100, 1) if r1 else None,
                 "cl": round(sum(c["hasil"]["kena_cl"] for c in r1) / len(r1) * 100, 1) if r1 else None},
        "per_ciri": per_ciri, "akurasi_tren": akurasi_tren, "kurva": kurva, "model": model,
        "jumlah": {"beli": len(beli), "tren": len(tren), "model": sum(c["jenis"] == "model" for c in cat),
                   "hari": len({c["tanggal"] for c in cat}),
                   "menunggu": sum(c["status"] in ("menunggu", "berjalan") for c in cat if c["jenis"] != "model")},
    }


def main():
    k = cfg.KELUAR
    p_riwayat = k / "prediksi" / "riwayat.json"
    riwayat = baca(p_riwayat) or pulihkan_dari_situs() or {"versi": 1, "catatan": []}
    cat = {c["id"]: c for c in riwayat["catatan"]}

    rk = baca(k / "ringkasan.json")
    if not rk:
        print("Prediksi: ringkasan belum ada, dilewati.")
        return
    sp = baca(k / "stockpick.json", {})
    fund = {f["kode"]: f for f in (baca(k / "fundamental.json", {}) or {}).get("saham", [])}

    # 1) nilai catatan yang belum selesai
    simpan = {}
    for c in cat.values():
        if c["status"] == "selesai":
            continue
        L = lilin(c["kode"], simpan)
        if L:
            {"beli": nilai_beli, "tren": nilai_tren, "model": nilai_model}[c["jenis"]](c, L)

    # 2) tambah catatan hari ini (id unik: data tanggal yang sama tidak terhitung dua kali)
    n_baru = 0
    for c in catat_hari_ini(rk, sp, fund) + catat_model(baca(k / "model.json")):
        if c["id"] not in cat:
            cat[c["id"]] = c
            n_baru += 1

    semua = sorted(cat.values(), key=lambda c: (c["tanggal"], c["kode"]))
    p_riwayat.parent.mkdir(parents=True, exist_ok=True)
    p_riwayat.write_text(json.dumps({"versi": 1, "catatan": semua}, ensure_ascii=False, separators=(",", ":")))

    st = statistik(semua)
    beli_akhir = [c for c in semua if c["jenis"] == "beli"][-300:]
    (k / "prediksi.json").write_text(json.dumps({
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "tanggal_data": rk["tanggal_data"],
        "statistik": st, "beli": beli_akhir,
        "tren_terbaru": [c for c in semua if c["jenis"] == "tren"][-400:],
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"Prediksi: {n_baru} catatan baru, total {len(semua)} ({st['jumlah']['hari']} hari), "
          f"{st['jumlah']['menunggu']} menunggu/berjalan.")


if __name__ == "__main__":
    main()
