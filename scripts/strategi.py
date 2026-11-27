"""Strategi utama harian (hasil riset 3 putaran, data 5 tahun, uji 2024-01 s.d. 2026-11 tanpa bias semesta).

Strategi B (utama)  : di antara saham layak (nilai transaksi rata-rata 20 hari >= Rp1 M, harga >= Rp50,
                      ada transaksi) yang kenaikan 20 harinya <= 100%, urutkan dengan
                      peringkat(kenaikan 20 hari) + peringkat(model peringkat antarsaham). Ambil 3 teratas.
Strategi A (pembanding): kenaikan 20 hari terbesar (<= 100%) tanpa jejak distribusi 5 hari. Ambil 3 teratas.
Keduanya hanya dibeli saat IHSG di atas MA20. Beli di pembukaan, batas rugi -5%, jual paling lambat
penutupan hari ke-3.

Model peringkat: HistGradientBoostingRegressor, sasaran = peringkat hasil transaksi (cara di atas) di antara
saham pada hari yang sama, hanya memakai ciri saham (tanpa ciri pasar/global). Dilatih ulang setiap hari
dengan seluruh riwayat 5 tahun yang sudah diketahui hasilnya.

Hasil uji (per transaksi, setelah biaya):
  B: rata-rata +0,60%, menang 49%, untung total/rugi total 1,41; 2024 -0,18%, 2025 +1,42%, 2026 +0,21%
  A: rata-rata +0,95%, menang 38%, untung total/rugi total 1,32; 2024 +0,55%, 2025 +2,04%, 2026 -0,38%
  Aturan J (lama): rata-rata -0,23%, menang 36%.
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
    "B": {"rata": 0.60, "menang": 49, "pf": 1.41, "tahun": {"2024": -0.18, "2025": 1.42, "2026": 0.21}},
    "A": {"rata": 0.95, "menang": 38, "pf": 1.32, "tahun": {"2024": 0.55, "2025": 2.04, "2026": -0.38}},
    "J": {"rata": -0.23, "menang": 36, "pf": 0.91},
    "periode": "Jan 2024 – Nov 2026",
}


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
    out = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "tanggal": str(pd.Timestamp(t_akhir).date()),
        "pasar_mendukung": pasar_naik,
        "B": B, "A": A,
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
