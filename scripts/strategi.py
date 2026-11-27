"""Strategi utama harian (hasil riset 3 putaran, data 5 tahun, uji 2024-01 s.d. 2026-11 tanpa bias semesta).

Strategi B (utama)  : di antara saham layak (nilai transaksi rata-rata 20 hari >= Rp1 M, harga >= Rp50,
                      ada transaksi) yang kenaikan 20 harinya <= 100%, urutkan dengan
                      peringkat(kenaikan 20 hari) + peringkat(model peringkat antarsaham). Ambil 3 teratas.
Strategi A (pembanding): kenaikan 20 hari terbesar (<= 100%) tanpa jejak distribusi 5 hari. Ambil 3 teratas.
Keduanya hanya dibeli saat IHSG di atas MA20. Cara trading (riset putaran 4): antrean beli di harga penutupan
atau lebih rendah (hanya terisi bila harga besok turun ke sana), batas rugi -5%, tahan selama penutupan di atas
MA10; bila penutupan di bawah MA10 (mulai hari kedua) dijual di pembukaan berikutnya; paling lama 20 hari.

Model peringkat: HistGradientBoostingRegressor, sasaran = peringkat hasil transaksi (cara di atas) di antara
saham pada hari yang sama, hanya memakai ciri saham (tanpa ciri pasar/global). Dilatih ulang setiap hari
dengan seluruh riwayat 5 tahun yang sudah diketahui hasilnya.

Hasil uji dengan cara di atas (per transaksi, setelah biaya; riset_model4/4b):
  B: rata-rata +3,18%, menang 38%, rata-rata untung +13,3% vs rugi -3,0% (~1:4,5), PF 2,73;
     portofolio 3 slot: 2024 +34%, 2025 +182%, 2026 -4%. Tanpa 5% transaksi terbaik rata-rata ~0%.
  A: rata-rata +2,79%, menang 31%, PF 1,82.
  Pembanding cara lama (beli pembukaan, jual hari ke-3): B +0,60%, A +0,95%, aturan J -0,23%.
  Target tetap 1:1/1:2/1:3 selalu lebih buruk daripada keluar di bawah MA10. Pola candlestick tidak
  menambah ketepatan (model + pola: +0,26% vs +0,60%).
Hasil: <DATA_KELUAR>/strategi.json
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
import riset_model as rm  # noqa: E402

WIB = timezone(timedelta(hours=7))
K_UTAMA, K_CADANGAN = 3, 2
UJI = {
    "B": {"rata": 3.18, "menang": 38, "pf": 2.73, "rata_untung": 13.3, "rata_rugi": -3.0,
          "tahun": {"2024": 34.0, "2025": 181.7, "2026": -4.1}},
    "A": {"rata": 2.79, "menang": 31, "pf": 1.82},
    "J": {"rata": -0.23, "menang": 36, "pf": 0.91},
    "periode": "Jan 2024 – Nov 2026",
    "catatan": "Untung berasal dari sedikit saham yang naik besar: tanpa 5% transaksi terbaik rata-rata sekitar 0%, "
               "dan 7 dari 12 kuartal rugi kecil. 2026 sejauh ini -4%.",
}


MAKS_UNGGULAN, MASUK_PERINGKAT, BERTAHAN_PERINGKAT = 10, 8, 20


def susun_unggulan(h, layak, bahaya, tgl):
    """Daftar saham unggulan harian (maks 10) dengan status baru/bertahan/keluar.

    Masuk  : peringkat skor B <= 8 di antara saham layak dan harga di atas MA20.
    Bertahan: sudah di daftar, peringkat <= 20, harga masih di atas MA20, tetap layak.
    Keluar : selain itu (alasan dicatat). Riwayat disimpan di <DATA_KELUAR>/unggulan.json."""
    p = cfg.KELUAR / "unggulan.json"
    lama = json.loads(p.read_text()) if p.exists() else {}
    riwayat = lama.get("riwayat", {})
    sebelum = sorted(t for t in riwayat if t < tgl)
    kemarin = {x["kode"]: x for x in riwayat[sebelum[-1]]} if sebelum else {}
    urut = layak.sort_values("skor_B", ascending=False).reset_index(drop=True)
    urut["peringkat"] = np.arange(1, len(urut) + 1)
    info = {r["kode"]: r for _, r in urut.iterrows()}
    semua = {r["kode"]: r for _, r in h.iterrows()}
    daftar, keluar = [], []
    for k, x in kemarin.items():
        r = info.get(k)
        if r is not None and r["peringkat"] <= BERTAHAN_PERINGKAT and r["ma20"] >= 0:
            daftar.append({"kode": k, "status": "bertahan", "sejak": x["sejak"]})
            continue
        if k not in semua:
            alasan = "tidak lagi memenuhi syarat likuid (nilai transaksi < Rp1 M, harga < Rp50, atau tanpa transaksi)"
        elif k in bahaya:
            alasan = "fundamental bermasalah: " + ", ".join(bahaya[k])
        elif semua[k]["r20"] > 1.0:
            alasan = "sudah naik lebih dari 100% dalam 20 hari (rawan aksi jual)"
        elif semua[k]["ma20"] < 0:
            alasan = "harga turun di bawah MA20 (tren melemah)"
        else:
            alasan = f"peringkat turun ke #{int(r['peringkat'])} dari {len(urut)} (batas bertahan #{BERTAHAN_PERINGKAT})"
        keluar.append({"kode": k, "sejak": x["sejak"], "alasan": alasan, "tutup": float(semua[k]["tutup"]) if k in semua else None})
    ada = {x["kode"] for x in daftar}
    for _, r in urut[(urut["peringkat"] <= MASUK_PERINGKAT) & (urut["ma20"] >= 0)].iterrows():
        if r["kode"] not in ada:
            daftar.append({"kode": r["kode"], "status": "baru", "sejak": tgl})
            ada.add(r["kode"])
    daftar.sort(key=lambda x: info[x["kode"]]["peringkat"])
    for x in daftar[MAKS_UNGGULAN:]:
        keluar.append({"kode": x["kode"], "sejak": x["sejak"], "alasan": "tergeser saham dengan peringkat lebih tinggi (maks 10)",
                       "tutup": float(info[x["kode"]]["tutup"])})
    daftar = daftar[:MAKS_UNGGULAN]
    tgl_riw = sorted(riwayat) + ([tgl] if tgl not in riwayat else [])
    for x in daftar:
        r = info[x["kode"]]
        x.update({"peringkat": int(r["peringkat"]), "dari": int(len(urut)), "skor": round(float(r["skor_B"]) * 50, 1),
                  "tutup": float(r["tutup"]), "r20": round(float(r["r20"]) * 100, 1), "r5": round(float(r["r5"]) * 100, 1),
                  "di_atas_ma20": round(float(r["ma20"]) * 100, 1), "pk_model": round(float(r["pk_model"]) * 100, 0),
                  "distribusi": bool(r["distribusi"]), "sektor": r["sektor"],
                  "hari": sum(1 for t in tgl_riw if x["sejak"] <= t <= tgl)})
    riwayat[tgl] = [{"kode": x["kode"], "sejak": x["sejak"]} for x in daftar]
    riwayat = {t: riwayat[t] for t in sorted(riwayat)[-60:]}
    hasil = {"tanggal": tgl, "daftar": daftar, "keluar": keluar, "pembanding": sebelum[-1] if sebelum else None,
             "aturan": {"maks": MAKS_UNGGULAN, "masuk": MASUK_PERINGKAT, "bertahan": BERTAHAN_PERINGKAT}}
    p.write_text(json.dumps({**hasil, "riwayat": riwayat}, ensure_ascii=False, separators=(",", ":")))
    print(f"Unggulan: {len(daftar)} saham ({sum(x['status'] == 'baru' for x in daftar)} baru), {len(keluar)} keluar")
    return hasil


def main():
    t0 = time.time()
    d, CIRI, _, _ = rm.bangun_data(pakai_global=False)
    ciri = [c for c in CIRI if not c.startswith(("ihsg_", "luas_", "g_")) and c != "hari"]
    lat = d[d["layak"] & d["hasil"].notna()].copy()
    lat["pk_hasil"] = lat.groupby("t")["hasil"].rank(pct=True)
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_depth=5, min_samples_leaf=300,
                                      l2_regularization=1.0, random_state=0).fit(lat[ciri], lat["pk_hasil"])
    t_akhir = d["t"].max()
    h = d[(d["t"] == t_akhir) & d["layak"]].copy()
    h["s_peringkat"] = m.predict(h[ciri])
    pasar_naik = bool((h["ihsg_ma20"] > 0).iloc[0]) if len(h) else False

    # saringan pengaman fundamental (rugi bersih, arus kas negatif, Piotroski rendah)
    bahaya = {}
    p = cfg.KELUAR / "fundamental.json"
    if p.exists():
        for f in json.loads(p.read_text()).get("saham", []):
            if f.get("bahaya"):
                bahaya[f["kode"]] = f["bahaya"]
    layak = h[(h["r20"] <= 1.0) & ~h["kode"].isin(bahaya)].copy()
    layak["pk_r20"] = layak["r20"].rank(pct=True)
    layak["pk_model"] = layak["s_peringkat"].rank(pct=True)
    layak["skor_B"] = layak["pk_r20"] + layak["pk_model"]

    def baris(r, strategi, urutan):
        return {"kode": r["kode"], "strategi": strategi, "urutan": urutan, "tutup": float(r["tutup"]),
                "r20": round(float(r["r20"]) * 100, 1), "pk_r20": round(float(r.get("pk_r20", np.nan)) * 100, 0),
                "pk_model": round(float(r.get("pk_model", np.nan)) * 100, 0),
                "rv1": round(float(r["rv1"]), 2), "distribusi": bool(r["distribusi"]), "cmf20": round(float(r["cmf20"]), 3),
                "sektor": r["sektor"], "utama": urutan <= K_UTAMA}

    B = [baris(r, "B", i + 1) for i, (_, r) in enumerate(layak.nlargest(K_UTAMA + K_CADANGAN, "skor_B").iterrows())]
    A_pool = layak[layak["distribusi"] == 0]
    A = [baris(r, "A", i + 1) for i, (_, r) in enumerate(A_pool.nlargest(K_UTAMA, "r20").iterrows())]
    tersaring = sorted(set(h.nlargest(15, "r20")["kode"]) & set(bahaya))
    unggulan = susun_unggulan(h, layak, bahaya, str(pd.Timestamp(t_akhir).date()))
    out = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "tanggal": str(pd.Timestamp(t_akhir).date()),
        "pasar_mendukung": pasar_naik,
        "B": B, "A": A, "unggulan": unggulan,
        "tersaring": [{"kode": k, "alasan": bahaya[k]} for k in tersaring],
        "n_layak": int(len(layak)), "n_latih": int(len(lat)),
        "uji": UJI,
        "aturan": __doc__.split("Strategi B (utama)")[1].split("Hasil:")[0].strip(),
    }
    (cfg.KELUAR / "strategi.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"Strategi: data {out['tanggal']}, pasar {'mendukung' if pasar_naik else 'lemah'}, "
          f"{len(layak)} saham layak, model dilatih {len(lat):,} baris ({time.time() - t0:.0f} dtk)")


if __name__ == "__main__":
    main()
