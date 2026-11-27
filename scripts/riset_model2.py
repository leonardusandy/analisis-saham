"""Riset putaran 2: apakah keunggulan momentum nyata atau hanya ditopang segelintir saham liar?

1. Ketahanan momentum: rata-rata bila hasil dibatasi +30%, sumbangan 5% transaksi terbaik,
   per tahun, per kelompok harga, tanpa saham yang naik > 100% dalam 20 hari, tanpa yang dekat ARA.
2. Variasi momentum: periode 5/10/20/60 hari, dengan konfirmasi volume / akumulasi / aturan J.
3. Model peringkat antarsaham (tanpa ciri pasar): sasaran = peringkat hasil transaksi di hari itu.
4. Realisme portofolio: modal dibagi ke posisi yang berjalan bersamaan; kurva modal, penurunan
   terdalam (drawdown), bulan terburuk.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import riset_model as rm  # noqa: E402

MULAI = rm.MULAI_UJI
BATAS = 0.30  # pembatas hasil per transaksi untuk uji ketahanan


def ringkas(r, nama=""):
    r = np.asarray(pd.Series(r).dropna()) * 100
    if len(r) < 5:
        return {"strategi": nama, "n": len(r)}
    m, k = r[r > 0], r[r <= 0]
    urut = np.sort(r)[::-1]
    top5 = urut[: max(1, len(r) // 20)].sum()
    return {"strategi": nama, "n": len(r), "rata%": round(r.mean(), 3),
            "rata_batas30%": round(np.clip(r, None, BATAS * 100).mean(), 3),
            "median%": round(float(np.median(r)), 2), "menang%": round(len(m) / len(r) * 100, 1),
            "PF": round(m.sum() / -k.sum(), 2) if k.sum() else None,
            "t": round(r.mean() / (r.std() / np.sqrt(len(r))), 2),
            "porsi_top5%": round(top5 / r.sum() * 100, 0) if r.sum() > 0 else None}


def portofolio(pil, kol="hasil", hari=3, K=3):
    """Modal dibagi K*hari slot; tiap hari K posisi baru, masing-masing 1/(K*hari) modal.
    Hasil harian = jumlah hasil posisi yang ditutup / (K*hari) (disederhanakan: dicatat di hari sinyal)."""
    per_hari = pil.groupby("t")[kol].sum() / (K * hari)
    kurva = (1 + per_hari).cumprod()
    dd = (kurva / kurva.cummax() - 1).min()
    bulan = per_hari.groupby(per_hari.index.to_period("M")).sum()
    tahun = per_hari.groupby(per_hari.index.year).apply(lambda x: (1 + x).prod() - 1)
    return {"total%": round((kurva.iloc[-1] - 1) * 100, 1), "drawdown%": round(dd * 100, 1),
            "bulan_terburuk%": round(bulan.min() * 100, 1), "bulan_positif%": round((bulan > 0).mean() * 100, 0),
            **{f"thn{y}%": round(v * 100, 1) for y, v in tahun.items()}}


def main():
    d, CIRI, KELOMPOK, t0 = rm.bangun_data()
    u = d[d["layak"] & d["hasil"].notna() & (d["t"] >= MULAI)].copy()
    u["naik_ihsg"] = u["ihsg_ma20"] > 0
    u["kelompok_harga"] = pd.cut(u["tutup"], [0, 200, 1000, 5000, 1e9], labels=["<200", "200-1rb", "1rb-5rb", ">5rb"])
    atr_kol = "hk_CL 1,5xATR jual hari-3"

    def top(df, kol, K=3, asc=False):
        return df.sort_values(kol, ascending=asc).groupby("t").head(K)

    print("\n=== 1. KETAHANAN MOMENTUM 20 HARI (top3, IHSG>MA20) ===")
    dasar = u[u["naik_ihsg"]]
    pil = top(dasar, "r20")
    print(pd.DataFrame([ringkas(pil["hasil"], "momentum20 top3"), ringkas(pil[atr_kol], "  (keluar ATR 1,5x)")]).to_string(index=False))
    print("\nPer kelompok harga:")
    print(pd.DataFrame([ringkas(g["hasil"], str(k)) for k, g in pil.groupby("kelompok_harga", observed=True)]).to_string(index=False))
    print("\nr20 rata-rata saham terpilih:", round(pil["r20"].mean() * 100, 1), "% ; median", round(pil["r20"].median() * 100, 1), "%")

    print("\n=== 2. VARIASI MOMENTUM (semua: IHSG>MA20, top3, keluar CL5% hari-3) ===")
    var = {
        "r20 (dasar)": (dasar, "r20"),
        "r5": (dasar, "r5"), "r10": (dasar, "r10"), "r60": (dasar, "r60"),
        "r20 tanpa r20>100%": (dasar[dasar["r20"] <= 1.0], "r20"),
        "r20 tanpa r20>50%": (dasar[dasar["r20"] <= 0.5], "r20"),
        "r20 harga>=200": (dasar[dasar["tutup"] >= 200], "r20"),
        "r20 nilai transaksi >= Rp5 M": (dasar[dasar["nilai"] >= np.log1p(5e9)], "r20"),
        "r20 tanpa dekat ARA hari ini": (dasar[dasar["dekat_ara"] == 0], "r20"),
        "r20 + volume >=1,2x": (dasar[dasar["rv1"] >= 1.2], "r20"),
        "r20 + CMF>0": (dasar[dasar["cmf20"] > 0], "r20"),
        "r20 + aturan J": (dasar[dasar["j"] == 1], "r20"),
        "r20 + tanpa distribusi": (dasar[dasar["distribusi"] == 0], "r20"),
        "r20 + harga di atas MA20 & MA50": (dasar[(dasar["ma20"] > 0) & (dasar["ma50"] > 0)], "r20"),
        "kekuatan relatif sektor (rel_sek20)": (dasar, "rel_sek20"),
    }
    baris, tahunan = [], []
    for nama, (df, kol) in var.items():
        p = top(df, kol)
        baris.append({**ringkas(p["hasil"], nama), "rata_ATR%": ringkas(p[atr_kol]).get("rata%")})
        for y, g in p.groupby(p["t"].dt.year):
            tahunan.append({"strategi": nama, "tahun": y, "rata%": ringkas(g["hasil"]).get("rata%")})
    print(pd.DataFrame(baris).sort_values("rata_batas30%", ascending=False).to_string(index=False))
    print("\nPer tahun:")
    print(pd.DataFrame(tahunan).pivot_table(index="strategi", columns="tahun", values="rata%").round(2).to_string())

    print("\n=== 3. MODEL PERINGKAT ANTARSAHAM (tanpa ciri pasar) ===")
    from sklearn.ensemble import HistGradientBoostingRegressor
    ciri_saham = [c for c in CIRI if not c.startswith(("ihsg_", "luas_", "g_")) and c != "hari"]
    lat = d[d["layak"] & d["hasil"].notna()].copy()
    lat["pk_hasil"] = lat.groupby("t")["hasil"].rank(pct=True)
    tgl = np.array(sorted(d["t"].unique()))
    kuartal = pd.period_range(u["t"].min(), u["t"].max(), freq="Q")
    u["s_peringkat"] = np.nan
    for q in kuartal:
        ia = np.searchsorted(tgl, np.datetime64(q.start_time))
        tr = lat[lat["t"] < tgl[max(0, ia - 5)]]
        te = u[(u["t"] >= q.start_time) & (u["t"] <= q.end_time)]
        if te.empty or len(tr) < 20000:
            continue
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_depth=5, min_samples_leaf=300,
                                          l2_regularization=1.0, random_state=0).fit(tr[ciri_saham], tr["pk_hasil"])
        u.loc[te.index, "s_peringkat"] = m.predict(te[ciri_saham])
        print(f"  kuartal {q} selesai ({time.time() - t0:.0f} dtk)", flush=True)
    uu = u.dropna(subset=["s_peringkat"])
    dd_ = uu[uu["naik_ihsg"]]
    hasil3 = []
    for nama, df, kol in [("peringkat top3 +IHSG", dd_, "s_peringkat"), ("peringkat top5 +IHSG", dd_, "s_peringkat"),
                          ("peringkat top3 tanpa saring", uu, "s_peringkat"),
                          ("momentum20 top3 +IHSG (periode sama)", dd_, "r20")]:
        K = 5 if "top5" in nama else 3
        p = top(df, kol, K)
        hasil3.append({**ringkas(p["hasil"], nama), **{f"{y}": ringkas(g["hasil"]).get("rata%") for y, g in p.groupby(p["t"].dt.year)}})
    # gabungan: momentum yang juga dinilai baik oleh model
    dd_ = dd_.copy()
    dd_["s_mix"] = dd_.groupby("t")["r20"].rank(pct=True) + dd_.groupby("t")["s_peringkat"].rank(pct=True)
    p = top(dd_, "s_mix")
    hasil3.append({**ringkas(p["hasil"], "momentum+peringkat top3 +IHSG"), **{f"{y}": ringkas(g["hasil"]).get("rata%") for y, g in p.groupby(p["t"].dt.year)}})
    print(pd.DataFrame(hasil3).to_string(index=False))

    print("\n=== 4. REALISME PORTOFOLIO (modal dibagi ke posisi yang berjalan bersamaan) ===")
    kandidat = {
        "momentum20 top3 +IHSG": top(u[u["naik_ihsg"]], "r20"),
        "momentum20 top3 +IHSG (r20<=100%)": top(u[u["naik_ihsg"] & (u["r20"] <= 1.0)], "r20"),
        "aturan J +IHSG (semua sinyal, maks 3/hari)": top(u[u["naik_ihsg"] & (u["j"] == 1)], "rv1"),
        "peringkat top3 +IHSG": top(uu[uu["naik_ihsg"]], "s_peringkat"),
        "acak 3/hari": u.sample(frac=1, random_state=0).groupby("t").head(3),
    }
    print(pd.DataFrame([{"strategi": k, **portofolio(v)} for k, v in kandidat.items()]).to_string(index=False))
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    main()
