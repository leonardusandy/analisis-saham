"""Riset putaran 3: buang bias pemilihan semesta.

Semesta di riset 1-2 memakai kapitalisasi HARI INI, sehingga saham yang melonjak pada 2024-2025
(dan kini besar) ikut terpilih, sedangkan yang jatuh tersisih. Di sini semesta tiap tahun uji Y
ditentukan HANYA dari data tahun Y-1: 250 saham dengan rata-rata nilai transaksi tertinggi pada
tahun sebelumnya (harga rata-rata >= Rp100). Juga diuji tambahan biaya selip 0,3% per transaksi.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import riset_model as rm  # noqa: E402
from riset_model2 import portofolio, ringkas  # noqa: E402

N_SEMESTA = 250
SELIP = 0.003


def main():
    d, CIRI, KELOMPOK, t0 = rm.bangun_data()
    d["tahun"] = d["t"].dt.year
    d["nilai_rp"] = np.expm1(d["nilai"])
    # semesta tahun Y = 250 saham ternilai tertinggi pada tahun Y-1 (harga rata-rata >= 100)
    st = d.groupby(["tahun", "kode"]).agg(nilai=("nilai_rp", "mean"), harga=("tutup", "mean")).reset_index()
    semesta = {}
    for y in (2024, 2025, 2026):
        x = st[(st["tahun"] == y - 1) & (st["harga"] >= 100)].nlargest(N_SEMESTA, "nilai")
        semesta[y] = set(x["kode"])
        print(f"Semesta {y} (dari data {y - 1}): {len(semesta[y])} saham")
    u = d[d["layak"] & d["hasil"].notna() & (d["t"] >= rm.MULAI_UJI)].copy()
    u = u[[k in semesta.get(y, set()) for k, y in zip(u["kode"], u["tahun"])]]
    u["naik_ihsg"] = u["ihsg_ma20"] > 0
    atr_kol = "hk_CL 1,5xATR jual hari-3"
    print(f"Baris uji: {len(u):,}")

    def top(df, kol, K=3):
        return df.sort_values(kol, ascending=False).groupby("t").head(K)

    # model peringkat (walk-forward, tanpa ciri pasar) dilatih pada semesta tahun sebelumnya juga
    from sklearn.ensemble import HistGradientBoostingRegressor
    ciri_saham = [c for c in CIRI if not c.startswith(("ihsg_", "luas_", "g_")) and c != "hari"]
    lat = d[d["layak"] & d["hasil"].notna()].copy()
    lat["pk_hasil"] = lat.groupby("t")["hasil"].rank(pct=True)
    tgl = np.array(sorted(d["t"].unique()))
    u["s_peringkat"] = np.nan
    for q in pd.period_range(u["t"].min(), u["t"].max(), freq="Q"):
        ia = np.searchsorted(tgl, np.datetime64(q.start_time))
        tr = lat[lat["t"] < tgl[max(0, ia - 5)]]
        te = u[(u["t"] >= q.start_time) & (u["t"] <= q.end_time)]
        if te.empty or len(tr) < 20000:
            continue
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_depth=5, min_samples_leaf=300,
                                          l2_regularization=1.0, random_state=0).fit(tr[ciri_saham], tr["pk_hasil"])
        u.loc[te.index, "s_peringkat"] = m.predict(te[ciri_saham])
    print(f"Model peringkat selesai ({time.time() - t0:.0f} dtk)")

    ih = u[u["naik_ihsg"]].copy()
    ih["s_mix"] = ih.groupby("t")["r20"].rank(pct=True) + ih.groupby("t")["s_peringkat"].rank(pct=True)
    ih100 = ih[ih["r20"] <= 1.0].copy()
    ih100["s_mix"] = ih100.groupby("t")["r20"].rank(pct=True) + ih100.groupby("t")["s_peringkat"].rank(pct=True)
    strategi = {
        "momentum20 top3 +IHSG": top(ih, "r20"),
        "momentum20 top3 +IHSG (r20<=100%)": top(ih100, "r20"),
        "momentum20 top3 +IHSG (r20<=100%, tanpa distribusi)": top(ih100[ih100["distribusi"] == 0], "r20"),
        "momentum20 top5 +IHSG (r20<=100%)": top(ih100, "r20", 5),
        "momentum+peringkat top3 +IHSG": top(ih.dropna(subset=["s_peringkat"]), "s_mix"),
        "momentum+peringkat top3 +IHSG (r20<=100%)": top(ih100.dropna(subset=["s_peringkat"]), "s_mix"),
        "peringkat top3 +IHSG": top(ih.dropna(subset=["s_peringkat"]), "s_peringkat"),
        "aturan J +IHSG (maks 3/hari)": top(ih[ih["j"] == 1], "rv1"),
        "aturan J +IHSG (semua sinyal)": ih[ih["j"] == 1],
        "acak (semua layak)": u,
    }
    baris, tahunan, porto = [], [], []
    for nama, p in strategi.items():
        r = ringkas(p["hasil"], nama)
        r["rata_ATR%"] = ringkas(p[atr_kol]).get("rata%")
        r["rata_selip%"] = ringkas(p["hasil"] - SELIP).get("rata%")
        baris.append(r)
        for y, g in p.groupby(p["t"].dt.year):
            tahunan.append({"strategi": nama, "tahun": y, "rata%": ringkas(g["hasil"]).get("rata%")})
        if "semua" not in nama:
            K = 5 if "top5" in nama else 3
            porto.append({"strategi": nama, **portofolio(p, K=K)})
            pp = p.copy()
            pp["hasil"] = pp["hasil"] - SELIP
            porto.append({"strategi": nama + " [selip 0,3%]", **portofolio(pp, K=K)})
    print("\n=== SEMESTA BEBAS BIAS: RINGKASAN PER TRANSAKSI ===")
    print(pd.DataFrame(baris).to_string(index=False))
    print("\nPer tahun (rata% per transaksi):")
    print(pd.DataFrame(tahunan).pivot_table(index="strategi", columns="tahun", values="rata%").round(2).to_string())
    print("\nPortofolio:")
    print(pd.DataFrame(porto).to_string(index=False))
    pil = strategi["momentum20 top3 +IHSG (r20<=100%)"]
    print("\nCiri saham terpilih (momentum r20<=100%): r20 median", round(pil["r20"].median() * 100, 1),
          "%, harga median", round(pil["tutup"].median()), ", nilai transaksi median Rp",
          round(np.expm1(pil["nilai"]).median() / 1e9, 1), "M")
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    main()
