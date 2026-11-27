"""Rencana kedua: swing trading saham berfundamental kuat (pegang 2-8 minggu).

Aturan (hasil riset_model5, uji Mei 2024 - Nov 2026, semesta bebas bias):
  Syarat tren   : harga > MA50, MA20 > MA50, MA50 naik dibanding 10 hari lalu, kenaikan 20 hari <= 100%.
  Fundamental   : Piotroski F-Score >= 6, ROE >= 10%, laba per saham positif, tidak ada tanda bahaya.
                  Laporan keuangan yang diunggah pengguna (lapkeu.json) ikut dipakai: putusan terbaru
                  "lemah"/"waspada" membuang saham itu.
  Urutan        : ROE tertinggi. 3 pilihan utama + 2 cadangan. Beli hanya saat IHSG di atas MA20.
  Masuk         : antrean beli di harga penutupan atau lebih rendah.
  Keluar        : batas rugi -8%, atau penutupan di bawah MA50 (dijual di pembukaan berikutnya), paling lama 40 hari bursa.
Hasil uji (portofolio 3 slot): +24,7% (2024 +13,9%, 2025 +22,6%, 2026 -10,7%), turun terdalam -25%,
rata-rata +1,2% per transaksi, menang 32%, rata-rata dipegang 17 hari. Pada periode yang sama IHSG -27,5%.
Hasil: <DATA_KELUAR>/swing.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
from analisis import bulatkan  # noqa: E402

WIB = timezone(timedelta(hours=7))
STOP = 0.08
UJI = {"porto": 24.7, "tahun": {"2024": 13.9, "2025": 22.6, "2026": -10.7}, "dd": -25.3, "rata": 1.2, "menang": 32,
       "hari": 17, "ihsg": -27.5, "periode": "Mei 2024 – Nov 2026",
       "catatan": "Pada periode uji, saham berfundamental lemah yang sedang naik justru memberi hasil jauh lebih besar "
                  "(tetapi jauh lebih berisiko dan dipengaruhi bias data). Swing fundamental lebih tahan saat pasar turun, "
                  "bukan cara tercepat mencari untung."}


def baca(p, bawaan=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:  # noqa: BLE001
        return bawaan


def main():
    k = cfg.KELUAR
    rk = baca(k / "ringkasan.json")
    fund = {f["kode"]: f for f in (baca(k / "fundamental.json", {}) or {}).get("saham", [])}
    lk = (baca(k / "lapkeu.json", {}) or {}).get("saham", {})
    if not rk:
        print("Swing: ringkasan belum ada, dilewati.")
        return
    t = rk["tanggal_data"]
    calon, dibuang = [], []
    for s in rk["saham"]:
        if s.get("tanggal") != t or (s.get("tutup") or 0) < 50 or (s.get("nilai_rata20_miliar") or 0) < 1:
            continue
        kode = s["kode"]
        d = baca(k / "saham" / f"{kode}.json")
        if not d or len(d.get("lilin", [])) < 70:
            continue
        c = [x["c"] for x in d["lilin"]]
        ma20, ma50 = sum(c[-20:]) / 20, sum(c[-50:]) / 50
        ma50_lalu = sum(c[-60:-10]) / 50
        r20, r60 = c[-1] / c[-21] - 1, c[-1] / c[-61] - 1
        if not (c[-1] > ma50 and ma20 > ma50 and ma50 > ma50_lalu and r20 <= 1.0):
            continue
        f = fund.get(kode, {})
        up = (lk.get(kode) or [None])[0]
        alasan_buang = []
        if f.get("bahaya"):
            alasan_buang.append(", ".join(f["bahaya"]))
        if up and up.get("putusan") in ("lemah", "waspada"):
            alasan_buang.append(f"laporan unggahan {up['periode']}: {up['putusan']}")
        pio, roe, eps = f.get("piotroski"), f.get("roe"), f.get("eps")
        if up and up.get("putusan") == "kuat" and (up.get("rasio") or {}).get("roe") is not None:
            roe = up["rasio"]["roe"]  # laporan terbaru unggahan pengguna lebih baru dari Yahoo
        lolos = pio is not None and pio >= 6 and roe is not None and roe >= 10 and (eps is None or eps > 0)
        if alasan_buang:
            if lolos:
                dibuang.append({"kode": kode, "alasan": alasan_buang})
            continue
        if not lolos:
            continue
        atr = s.get("atr") or c[-1] * 0.03
        hi = bulatkan(c[-1], "bawah")
        lo = bulatkan(max(ma20, c[-1] - 0.5 * atr), "bawah")
        calon.append({
            "kode": kode, "nama": f.get("nama") or s.get("nama"), "sektor": f.get("sektor") or s.get("sektor"),
            "tutup": c[-1], "entry": [min(lo, hi), hi], "cl": bulatkan(hi * (1 - STOP), "atas"),
            "ma20": round(ma20, 1), "ma50": round(ma50, 1), "roe": round(roe, 1), "piotroski": pio,
            "piotroski_terdata": f.get("piotroski_terdata"), "per": f.get("per"), "pbv": f.get("pbv"),
            "r20": round(r20 * 100, 1), "r60": round(r60 * 100, 1),
            "lapkeu": {"periode": up["periode"], "putusan": up["putusan"]} if up else None,
            "peringatan": f.get("peringatan") or [],
        })
    calon.sort(key=lambda x: -x["roe"])
    for i, x in enumerate(calon[:5]):
        x["urutan"], x["utama"] = i + 1, i < 3
    hasil = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "tanggal": t,
        "pasar_mendukung": bool(rk.get("pasar_mendukung")), "pilihan": calon[:5], "n_lolos": len(calon),
        "tersaring": dibuang[:20], "uji": UJI, "aturan": __doc__,
    }
    (k / "swing.json").write_text(json.dumps(hasil, ensure_ascii=False, separators=(",", ":")))
    print(f"Swing: data {t}, {len(calon)} saham lolos tren + fundamental, {len(dibuang)} dibuang saringan.")


if __name__ == "__main__":
    main()
