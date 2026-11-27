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

import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

WIB = timezone(timedelta(hours=7))
SITUS = os.environ.get("SITUS_WEB", "https://leonardusandy.github.io/analisis-saham/")
HARI_BELI, HARI_MODEL, HARI_TREN = 20, 3, 5


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


def nilai_h1(c: dict, L: list) -> None:
    """Penilaian di penutupan berikutnya (1 hari bursa setelah prediksi)."""
    if "h1" in c:
        return
    tgl = [x["t"] for x in L]
    if c["tanggal"] not in tgl:
        return
    i = tgl.index(c["tanggal"])
    if i + 1 >= len(L):
        return
    n = L[i + 1]
    c["h1"] = {"t": n["t"], "o": n["o"], "h": n["h"], "l": n["l"], "c": n["c"],
               "pct": round((n["c"] / L[i]["c"] - 1) * 100, 2)}


def nilai_posisi(c: dict, L: list) -> None:
    """Keputusan posisi pengguna dinilai di penutupan berikutnya:
    jual/waspada benar bila harga turun; tahan benar bila harga naik atau tetap."""
    h = c.get("h1")
    if not h:
        return
    c["status"] = "selesai"
    c["benar"] = h["pct"] < 0 if c["keputusan"] in ("jual", "waspada") else h["pct"] >= 0


def catat_posisi() -> list[dict]:
    """Keputusan posisi yang dikirim halaman Rencana (terenkripsi dengan sandi web)."""
    data = os.environ.get("POSISI_TERKUNCI", "").strip()
    sandi = os.environ.get("SANDI_WEB", "")
    if not data or not sandi:
        return []
    try:
        import base64
        from enkripsi import buka
        isi = buka(base64.b64decode(data), sandi)
    except Exception as e:  # noqa: BLE001
        print("  ! kiriman posisi tidak bisa dibuka:", e)
        return []
    t = isi.get("tanggal")
    hasil = []
    for x in isi.get("posisi", [])[:50]:
        k = str(x.get("kode", "")).upper()[:6]
        if not t or not k or x.get("keputusan") not in ("jual", "waspada", "tahan"):
            continue
        hasil.append({"id": f"{t}|{k}|posisi|{x.get('tgl', '')}", "jenis": "posisi", "tanggal": t, "kode": k,
                      "status": "menunggu", "keputusan": x["keputusan"], "tgl_beli": x.get("tgl"),
                      "beli": x.get("beli"), "tutup": x.get("tutup"), "stop": x.get("stop"), "target": x.get("target")})
    print(f"  posisi pengguna diterima: {len(hasil)} keputusan untuk data {t}")
    return hasil


def penilaian_harian(semua: list[dict]) -> list[dict]:
    """Ringkasan penilaian penutupan berikutnya untuk setiap tanggal prediksi."""
    per = defaultdict(list)
    for c in semua:
        if c.get("h1"):
            per[c["tanggal"]].append(c)
    hasil = []
    for t in sorted(per):
        v = per[t]
        mdl = [c for c in v if c["jenis"] == "model"]
        beli = [c for c in v if c["jenis"] == "beli"]
        tren = [c for c in v if c["jenis"] == "tren"]
        pos = [c for c in v if c["jenis"] == "posisi"]
        d = {"tanggal": t, "dinilai": v[0]["h1"]["t"]}
        if pos:
            d["posisi"] = [{"kode": c["kode"], "keputusan": c["keputusan"], "pct": c["h1"]["pct"], "benar": c.get("benar")}
                           for c in pos]
        if mdl:
            med = float(np.median([c["h1"]["pct"] for c in mdl]))
            rel = [c for c in mdl if c.get("p_rel") is not None]
            urut = sorted(rel, key=lambda c: -c["p_rel"])
            n5 = max(1, len(urut) // 5)
            d["model"] = {
                "n": len(mdl),
                "arah_benar": round(sum((c["p"] >= 50) == (c["h1"]["pct"] > 0) for c in mdl) / len(mdl) * 100, 1),
                "naik_diperkirakan": sum(c["p"] >= 50 for c in mdl),
                "naik_nyata": sum(c["h1"]["pct"] > 0 for c in mdl),
                "rel_benar": round(sum((c["p_rel"] >= 50) == (c["h1"]["pct"] > med) for c in rel) / len(rel) * 100, 1) if rel else None,
                "atas20": round(sum(c["h1"]["pct"] for c in urut[:n5]) / n5, 2) if rel else None,
                "bawah20": round(sum(c["h1"]["pct"] for c in urut[-n5:]) / n5, 2) if rel else None,
                "median": round(med, 2),
            }
        if beli:
            d["beli"] = [{
                "kode": c["kode"], "dipilih": c.get("dipilih", []), "pct": c["h1"]["pct"],
                "buka": c["h1"]["o"], "tutup": c["h1"]["c"], "entry": (c.get("rencana") or {}).get("entry"),
                "bisa_beli": bool((c.get("rencana") or {}).get("entry") and c["h1"]["l"] <= c["rencana"]["entry"][1]),
                "benar": c["h1"]["pct"] > 0,
            } for c in sorted(beli, key=lambda c: (not c.get("dipilih"), c["kode"]))]
        if tren:
            def akr(arr, uji):
                return {"n": len(arr), "benar": round(sum(uji(c["h1"]["pct"]) for c in arr) / len(arr) * 100, 1) if arr else None}
            d["tren"] = {
                "uptrend": akr([c for c in tren if c["prediksi"] == "up"], lambda x: x > 0),
                "sideways": akr([c for c in tren if c["prediksi"] == "side"], lambda x: abs(x) <= 2),
                "keluar": akr([c for c in tren if c["prediksi"] == "keluar"], lambda x: x < 0),
            }
        hasil.append(d)
    return hasil[-60:]


def nilai_beli(c: dict, L: list, stop_pct: float | None = None, ma: int = 10, maks: int | None = None) -> None:
    """Cara trading (hasil riset putaran 4): antrean beli di batas atas rentang beli (harga penutupan hari
    sinyal). Antrean hanya terisi bila harga besok turun sampai harga antrean; harga beli = min(pembukaan,
    harga antrean). Batas rugi -5% dari harga beli. Saham ditahan selama penutupan >= MA10; bila penutupan
    di bawah MA10 (mulai hari kedua), dijual di pembukaan hari berikutnya. Paling lama 20 hari bursa."""
    tgl = [x["t"] for x in L]
    if c["tanggal"] not in tgl:
        return
    i = tgl.index(c["tanggal"])
    maks = maks or HARI_BELI
    ke = L[i + 1:i + 1 + maks]
    if not ke:
        c["status"] = "menunggu"
        return
    r = c.get("rencana") or {}
    antrean = ((r.get("entry") or [None, None])[1]) or L[i]["c"]
    d1 = ke[0]
    if not d1["o"] or d1["l"] > antrean:
        c["hasil"] = {"terisi": False, "antrean": antrean, "sampai": d1["t"]}
        c["status"] = "tidak terisi"
        c.pop("benar", None)
        return
    beli = min(d1["o"], antrean)
    stop = beli * (1 - (stop_pct or cfg.STOP_PERSEN))
    keluar, cara, hari_keluar = None, None, None
    for n, x in enumerate(ke):
        j = i + 1 + n
        if n > 0 and x["o"] <= stop:
            keluar, cara, hari_keluar = x["o"], "batas rugi (buka di bawah)", x["t"]
            break
        if x["l"] <= stop:
            keluar, cara, hari_keluar = stop, "batas rugi", x["t"]
            break
        if n > 0 and j >= ma - 1:
            rata = sum(y["c"] for y in L[j - ma + 1:j + 1]) / ma
            if x["c"] < rata:
                if j + 1 < len(L):
                    keluar, cara, hari_keluar = L[j + 1]["o"], f"tutup di bawah MA{ma}", L[j + 1]["t"]
                else:
                    cara = f"jual besok (tutup di bawah MA{ma})"
                break
    selesai = keluar is not None or (cara is None and len(ke) >= maks)
    if keluar is None:
        keluar, hari_keluar = ke[-1]["c"], ke[-1]["t"]
        if cara is None:
            cara = f"batas {maks} hari" if selesai else f"berjalan hari ke-{len(ke)}"
    hasil = (keluar * (1 - cfg.BIAYA_JUAL)) / (beli * (1 + cfg.BIAYA_BELI)) - 1
    tinggi = max(x["h"] for x in ke)
    c["hasil"] = {
        "terisi": True, "beli": round(beli, 1), "keluar": round(keluar, 1), "cara": cara, "pct": round(hasil * 100, 2),
        "naik_maks_pct": round((tinggi / beli - 1) * 100, 2), "sesuai_entry": True,
        "kena_r1": bool(r.get("r1") and tinggi >= r["r1"]),
        "kena_r2": bool(r.get("r2") and tinggi >= r["r2"]),
        "kena_cl": cara.startswith("batas rugi"),
        "sampai": hari_keluar if selesai else ke[-1]["t"], "aturan": f"antrean+MA{ma}",
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
    ke = L[i + 1:i + 1 + HARI_MODEL]
    if not ke:
        return
    ubah = (ke[-1]["c"] / L[i]["c"] - 1) * 100
    c["hasil"] = {"pct": round(ubah, 2), "hari": len(ke), "sampai": ke[-1]["t"]}
    if len(ke) >= HARI_MODEL:
        c["status"] = "selesai"
        c["benar"] = (c["p"] >= 50) == (ubah > 0)
    else:
        c["status"] = "berjalan"


def catat_swing(sw: dict) -> list[dict]:
    """Pilihan swing fundamental hari ini (utama + cadangan) untuk uji kertas."""
    if not sw or not sw.get("pilihan"):
        return []
    t = sw["tanggal"]
    return [{"id": f"{t}|{x['kode']}|swing", "jenis": "swing", "tanggal": t, "kode": x["kode"], "status": "menunggu",
             "dipilih": ["S" if x.get("utama") else "S-cadangan"], "rencana": {"entry": x["entry"], "cl": x["cl"]},
             "tutup": x["tutup"], "fitur": {"ihsg_naik": bool(sw.get("pasar_mendukung")), "roe": x.get("roe"),
                                            "piotroski": x.get("piotroski")}} for x in sw["pilihan"]]


def catat_model(md: dict) -> list[dict]:
    if not md:
        return []
    t = md["tanggal"]
    return [{"id": f"{t}|{x['kode']}|model", "jenis": "model", "tanggal": t, "kode": x["kode"], "status": "menunggu",
             "p": x["p"], "keyakinan": x["keyakinan"], "p_rel": x.get("p_rel")} for x in md["prediksi"]]


def catat_hari_ini(rk: dict, sp: dict, fund: dict, st: dict | None = None) -> list[dict]:
    t = rk["tanggal_data"]
    ihsg_naik = bool(rk.get("pasar_mendukung"))
    st = st or {}
    tag_strategi = {}
    if st.get("tanggal") == t:
        for nama in ("B", "A"):
            for x in st.get(nama, []):
                tag_strategi.setdefault(x["kode"], []).append(nama if x.get("utama", True) else nama + "-cadangan")
    pilih_analisa = {a["kode"]: a for a in (sp or {}).get("analisa", [])}
    kandidat = set(rk.get("kandidat", [])) | set(rk.get("kandidat_tunda", []))
    baris_sp = {b["kode"]: b for b in (sp or {}).get("uptrend", []) + (sp or {}).get("sideways", [])}
    berita = baca(cfg.KELUAR / "berita.json", {}) or {}
    psi = (baca(cfg.KELUAR / "psikologi.json", {}) or {})
    psi = psi.get("saham", {}) if psi.get("tanggal") == t else {}
    offer = sorted((v["rasio_antrean"], k2) for k2, v in psi.items() if v.get("tutup_di") == "offer" and v.get("rasio_antrean") is not None)
    pers = {k2: (i + 1) / len(offer) for i, (_, k2) in enumerate(offer)}
    batas_b = (datetime.now(WIB) - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S")

    def hitung_berita(k):
        arr = (berita.get("per_saham") or {}).get(k, []) + [b for b in berita.get("pasar", []) if k in (b.get("kode") or [])]
        lihat, n = set(), {"neg_tp": 0, "pos_tp": 0, "neg_lain": 0}
        for b in arr:
            if b.get("judul") in lihat or (b.get("waktu") or "") < batas_b:
                continue
            lihat.add(b.get("judul"))
            lab = next((a.get("sentimen") for a in (b.get("analisis") or []) if a.get("kode") == k), None) or (b.get("sentimen") or {}).get("label")
            if lab == "negatif":
                n["neg_tp" if b.get("terpercaya") else "neg_lain"] += 1
            elif lab == "positif" and b.get("terpercaya"):
                n["pos_tp"] += 1
        return n
    arah_sektor = {x["nama"]: x["arah"] for x in (sp or {}).get("sektor", [])}
    baru = []
    for s in rk["saham"]:
        if s.get("tanggal") != t or not s.get("likuid") or not (s.get("sinyal_j") or s["kode"] in tag_strategi):
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
            "dipilih": [x for x, ya in (("analisa", k in pilih_analisa), ("kandidat", k in kandidat)) if ya]
                       + tag_strategi.get(k, []) + (["J"] if s.get("sinyal_j") else []),
            "rencana": rencana, "tutup": s.get("tutup"),
            "fitur": {
                "ihsg_naik": ihsg_naik, "macd": bool(s.get("sinyal_macd")), "kualitas": bool(f.get("lolos_kualitas")),
                "bahaya": bool(f.get("bahaya")), "sektor": sektor, "sektor_arah": arah_sektor.get(sektor, "netral"),
                "lapis": s.get("lapis"), "lq45": bool(s.get("lq45")), "rsi": s.get("rsi"), "rasio_vol": s.get("rasio_vol"),
                "skor": s.get("skor"), "tingkat": b.get("tingkat"), "kuat": b.get("kuat"), "murah": b.get("murah"),
                "ubah_hari": s.get("perubahan_pct"), "ubah_20h": s.get("ubah_20h"), "nilai_miliar": s.get("nilai_rata20_miliar"),
                "berita": hitung_berita(k),
                "antrean": {"tutup_di": (psi.get(k) or {}).get("tutup_di"), "rasio": (psi.get(k) or {}).get("rasio_antrean"),
                            "persentil_offer": round(pers[k], 2) if k in pers else None, "rasio_lot": (psi.get(k) or {}).get("rasio_lot")},
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
        "Berita negatif media terpercaya (36 jam)": lambda c: "belum dicatat" if "berita" not in c["fitur"]
            else "ada" if c["fitur"]["berita"].get("neg_tp") else "tidak ada",
        "Sinyal antrean penutupan": lambda c: "belum dicatat" if not (c["fitur"].get("antrean") or {}).get("tutup_di")
            else "kuat (offer, 20% teratas)" if ((c["fitur"]["antrean"].get("persentil_offer") or 0) >= 0.8)
            else "lemah (offer, 20% terbawah)" if (c["fitur"]["antrean"].get("persentil_offer") is not None and c["fitur"]["antrean"]["persentil_offer"] <= 0.2)
            else "lainnya",
        "Berita positif media terpercaya (36 jam)": lambda c: "belum dicatat" if "berita" not in c["fitur"]
            else "ada" if c["fitur"]["berita"].get("pos_tp") else "tidak ada",
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
    pos = [c for c in cat if c["jenis"] == "posisi" and c.get("status") == "selesai"]
    posisi = {k: {"n": len(v), "benar": round(sum(c["benar"] for c in v) / len(v) * 100, 1) if v else None}
              for k, v in (("semua", pos), ("jual", [c for c in pos if c["keputusan"] in ("jual", "waspada")]),
                           ("tahan", [c for c in pos if c["keputusan"] == "tahan"]))}

    def akurasi(arr):
        return {"n": len(arr), "benar": round(sum(c["benar"] for c in arr) / len(arr) * 100, 1) if arr else None}
    per_hari = defaultdict(list)
    for c in mdl:
        per_hari[c["tanggal"]].append(c)
    # penilaian relatif: dibanding median perubahan semua saham pada tanggal yang sama
    rel, selisih = [], []
    for t, v in per_hari.items():
        v = [c for c in v if c.get("p_rel") is not None]
        if len(v) < 20:
            continue
        med = float(np.median([c["hasil"]["pct"] for c in v]))
        for c in v:
            c["benar_rel"] = (c["p_rel"] >= 50) == (c["hasil"]["pct"] > med)
            rel.append(c)
        urut = sorted(v, key=lambda c: -c["p_rel"])
        n5 = max(1, len(urut) // 5)
        selisih.append({"t": t, "atas": sum(c["hasil"]["pct"] for c in urut[:n5]) / n5,
                        "bawah": sum(c["hasil"]["pct"] for c in urut[-n5:]) / n5})
    model = {
        "relatif": {"n": len(rel), "benar": round(sum(c["benar_rel"] for c in rel) / len(rel) * 100, 1) if rel else None,
                    "hari": len(selisih),
                    "atas20": round(sum(x["atas"] for x in selisih) / len(selisih), 2) if selisih else None,
                    "bawah20": round(sum(x["bawah"] for x in selisih) / len(selisih), 2) if selisih else None},
        "semua": akurasi(mdl),
        "per_keyakinan": {y: akurasi([c for c in mdl if c["keyakinan"] == y]) for y in ("tinggi", "sedang", "rendah")},
        "per_arah": {"naik": akurasi([c for c in mdl if c["p"] >= 50]), "turun": akurasi([c for c in mdl if c["p"] < 50])},
        "harian": [{"t": t, **akurasi(v)} for t, v in sorted(per_hari.items())][-120:],
    }
    return {
        "beli_semua": ringkas(beli), "beli_dipilih": ringkas(pilih),
        # uji kertas per strategi (catatan lama tanpa label strategi dianggap aturan J)
        "per_strategi": {
            "B": ringkas([c for c in beli if "B" in c.get("dipilih", [])]),
            "B_saat_pasar_naik": ringkas([c for c in beli if "B" in c.get("dipilih", []) and c["fitur"].get("ihsg_naik")]),
            "A": ringkas([c for c in beli if "A" in c.get("dipilih", [])]),
            "J": ringkas([c for c in beli if "J" in c.get("dipilih", []) or not any(x in c.get("dipilih", []) for x in ("A", "B", "A-cadangan", "B-cadangan"))]),
            "S": ringkas([c for c in cat if c["jenis"] == "swing" and "S" in c.get("dipilih", [])]),
            "S_saat_pasar_naik": ringkas([c for c in cat if c["jenis"] == "swing" and "S" in c.get("dipilih", []) and c["fitur"].get("ihsg_naik")]),
        },
        "beli_analisa": ringkas([c for c in beli if "analisa" in c.get("dipilih", [])]),
        "antrean": {"terisi": sum(c.get("status") in ("selesai", "berjalan") for c in pilih),
                    "tidak_terisi": sum(c.get("status") == "tidak terisi" for c in pilih)},
        "kena": {"r1": round(sum(c["hasil"]["kena_r1"] for c in r1) / len(r1) * 100, 1) if r1 else None,
                 "r2": round(sum(c["hasil"]["kena_r2"] for c in r1) / len(r1) * 100, 1) if r1 else None,
                 "cl": round(sum(c["hasil"]["kena_cl"] for c in r1) / len(r1) * 100, 1) if r1 else None},
        "per_ciri": per_ciri, "akurasi_tren": akurasi_tren, "kurva": kurva, "model": model, "posisi": posisi,
        "jumlah": {"beli": len(beli), "tren": len(tren), "model": sum(c["jenis"] == "model" for c in cat),
                   "hari": len({c["tanggal"] for c in cat}),
                   "menunggu": sum(c["status"] in ("menunggu", "berjalan") for c in cat if c["jenis"] != "model"),
                   "swing": sum(c["jenis"] == "swing" for c in cat)},
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

    t_data = rk["tanggal_data"]
    # 0a) penilaian yang memakai harga SETELAH tanggal data terakhir (mis. candle belum final) dibatalkan
    for c in cat.values():
        h1 = c.get("h1")
        hs = c.get("hasil") or {}
        if (h1 and h1.get("t", "") > t_data) or (hs.get("sampai", "") > t_data):
            for x in ("h1", "hasil", "benar", "benar_rel"):
                c.pop(x, None)
            c["status"] = "menunggu"
    # 0b) proses ulang untuk tanggal data yang sama: catatan yang belum dinilai diganti yang terbaru
    for cid in [cid for cid, c in cat.items()
                if c["tanggal"] == t_data and c["jenis"] in ("beli", "tren", "model", "swing") and "h1" not in c]:
        del cat[cid]
    # 1) nilai catatan yang belum selesai
    simpan = {}
    for c in cat.values():
        if c["status"] == "selesai" and "h1" in c:
            continue
        L = lilin(c["kode"], simpan)
        if not L:
            continue
        nilai_h1(c, L)
        if c["status"] != "selesai":
            {"beli": nilai_beli, "tren": nilai_tren, "model": nilai_model, "posisi": nilai_posisi,
             "swing": lambda c, L: nilai_beli(c, L, 0.08, 50, 40)}[c["jenis"]](c, L)

    # 2) tambah catatan hari ini (id unik: data tanggal yang sama tidak terhitung dua kali)
    n_baru = 0
    for c in (catat_hari_ini(rk, sp, fund, baca(k / "strategi.json", {})) + catat_model(baca(k / "model.json"))
              + catat_swing(baca(k / "swing.json", {}))):
        if c["id"] not in cat:
            cat[c["id"]] = c
            n_baru += 1
    for c in catat_posisi():  # keputusan terbaru untuk hari yang sama menggantikan yang lama (bila belum dinilai)
        if c["id"] not in cat or "h1" not in cat[c["id"]]:
            cat[c["id"]] = c
            n_baru += 1
            L = lilin(c["kode"], simpan)
            if L:  # dikirim terlambat: langsung nilai bila harga hari berikutnya sudah ada
                nilai_h1(c, L)
                nilai_posisi(c, L)

    semua = sorted(cat.values(), key=lambda c: (c["tanggal"], c["kode"]))
    p_riwayat.parent.mkdir(parents=True, exist_ok=True)
    p_riwayat.write_text(json.dumps({"versi": 1, "catatan": semua}, ensure_ascii=False, separators=(",", ":")))

    st = statistik(semua)
    beli_akhir = [c for c in semua if c["jenis"] == "beli"][-300:]
    (k / "prediksi.json").write_text(json.dumps({
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "tanggal_data": rk["tanggal_data"],
        "statistik": st, "beli": beli_akhir, "harian": penilaian_harian(semua),
        "tren_terbaru": [c for c in semua if c["jenis"] == "tren"][-400:],
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"Prediksi: {n_baru} catatan baru, total {len(semua)} ({st['jumlah']['hari']} hari), "
          f"{st['jumlah']['menunggu']} menunggu/berjalan.")


if __name__ == "__main__":
    main()
