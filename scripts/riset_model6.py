"""Riset putaran 6: "psikologi pasar" dari data harian (pendekatan pembacaan bandar/antrean tanpa order book).

Ciri psikologi yang diuji (semua hanya memakai data sampai hari t):
  ARA terkunci / ARB terkunci, ARA beruntun, euforia (naik >= 5 hari beruntun & +25% dalam 5 hari),
  klimaks volume (volume >= 3x setelah naik > 30% dalam 20 hari), penolakan atas (sumbu atas >= 50% rentang
  dengan volume >= 1,5x), gap jebakan (buka > 2% di atas penutupan kemarin tetapi tutup < buka),
  kekuatan saat IHSG merah (rata-rata selisih dengan IHSG pada hari IHSG turun > 0,5%, 10 hari),
  tahan di hari merah (saham hijau saat IHSG turun > 1%), angka bulat (harga baru menembus 100/500/1000/5000),
  jarak ke batas fraksi harga.
Uji: (1) statistik tiap ciri terhadap hasil besok dan transaksi (cara Anda: antrean, CL 5%, keluar < MA10);
     (2) strategi B dengan dan tanpa ciri psikologi di model (walk-forward per kuartal).
Log hanya statistik gabungan.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import riset_model as rm  # noqa: E402
import riset_model4 as r4  # noqa: E402

pd.set_option("display.width", 300)
pd.set_option("display.max_rows", 200)


def tambah_psikologi(d: pd.DataFrame) -> list[tuple[str, str]]:
    g = d.groupby("kode", sort=False)
    o, h, l, c = d["buka"], d["tinggi"], d["rendah"], d["tutup"]
    c1 = g["tutup"].shift(1)
    ara = pd.Series(rm.batas_ara(c1.fillna(c).to_numpy()), index=d.index)
    r1 = c / c1 - 1
    rng = (h - l).replace(0, np.nan)
    rv = d["rv1"]
    d["ps_ara_kunci"] = ((r1 >= ara * 0.97) & (c >= h * 0.999)).astype(float)
    d["ps_arb_kunci"] = ((r1 <= -ara * 0.97 * 0.6) & (c <= l * 1.001)).astype(float)  # ARB lebih sempit (sekitar 15%)
    d["ps_ara_beruntun"] = g["ps_ara_kunci"].transform(lambda x: x.rolling(3).sum())
    naik = (r1 > 0).astype(float)
    d["_naik"] = naik
    d["ps_hari_naik"] = g["_naik"].transform(lambda x: x.groupby((x == 0).cumsum()).cumsum())
    d["ps_euforia"] = ((d["ps_hari_naik"] >= 5) & (d["r5"] >= 0.25)).astype(float)
    d["ps_klimaks_vol"] = ((rv >= 3) & (d["r20"] >= 0.30)).astype(float)
    d["ps_tolak_atas"] = (((h - np.maximum(o, c)) >= 0.5 * rng) & (rv >= 1.5)).astype(float)
    d["ps_gap_jebakan"] = ((o >= c1 * 1.02) & (c < o)).astype(float)
    rel = r1 - d["ihsg_r1"]
    merah = (d["ihsg_r1"] < -0.005).astype(float)
    d["_relm"], d["_m"] = rel.fillna(0) * merah, merah
    d["ps_kuat_saat_merah"] = (g["_relm"].transform(lambda x: x.rolling(10).sum())
                               / g["_m"].transform(lambda x: x.rolling(10).sum()).replace(0, np.nan))
    d["ps_hijau_saat_merah"] = ((d["ihsg_r1"] < -0.01) & (r1 > 0)).astype(float)
    bulat = np.select([c < 200, c < 2000, c < 10000], [100.0, 500.0, 1000.0], 5000.0)
    lv = np.floor(c / bulat) * bulat
    d["ps_tembus_bulat"] = ((c1 < lv) & (c >= lv) & (lv > 0)).astype(float)
    batas = np.select([c < 200, c < 500, c < 2000, c < 5000], [200.0, 500.0, 2000.0, 5000.0], np.nan)
    d["ps_jarak_fraksi"] = (batas / c - 1)
    nama = [("ps_ara_kunci", "ARA terkunci (tutup di batas atas)"), ("ps_arb_kunci", "ARB/turun tajam terkunci di bawah"),
            ("ps_euforia", "Euforia: naik >=5 hari & +25% dalam 5 hari"), ("ps_klimaks_vol", "Klimaks volume (>=3x setelah +30%/20 hari)"),
            ("ps_tolak_atas", "Penolakan atas bervolume (sumbu atas >= 50%)"), ("ps_gap_jebakan", "Gap jebakan (buka +2%, tutup < buka)"),
            ("ps_hijau_saat_merah", "Hijau saat IHSG turun > 1%"), ("ps_tembus_bulat", "Menembus angka bulat psikologis")]
    d.drop(columns=["_naik", "_relm", "_m"], inplace=True)
    return nama


def main():
    d, u, SET, H, acak, t0 = r4.siapkan(cetak_pola=False)
    nama = tambah_psikologi(d)
    kol = ["ps_ara_kunci", "ps_arb_kunci", "ps_ara_beruntun", "ps_hari_naik", "ps_euforia", "ps_klimaks_vol", "ps_tolak_atas",
           "ps_gap_jebakan", "ps_kuat_saat_merah", "ps_hijau_saat_merah", "ps_tembus_bulat", "ps_jarak_fraksi"]
    u = u.drop(columns=[c for c in kol if c in u.columns]).join(d[kol])

    # ---- 1. statistik tiap ciri (periode uji, semesta bebas bias)
    v = u[u["besok"].notna()].copy()
    v["selisih"] = v["besok"] - v.groupby("t")["besok"].transform("mean")
    print("\n=== 1. CIRI PSIKOLOGI: APA YANG TERJADI BESOK & 3 HARI (2024 s.d. sekarang) ===")
    rows = [{"ciri": "(semua, pembanding)", "n": len(v), "besok%": round(v["besok"].mean() * 100, 3), "selisih%": 0,
             "naik%": round((v["besok"] > 0).mean() * 100, 1), "trade3%": round(v["hasil"].mean() * 100, 2)}]
    for k, nm in nama:
        x = v[v[k] == 1]
        if len(x) < 30:
            rows.append({"ciri": nm, "n": len(x)})
            continue
        s = x["selisih"]
        rows.append({"ciri": nm, "n": len(x), "besok%": round(x["besok"].mean() * 100, 3), "selisih%": round(s.mean() * 100, 3),
                     "naik%": round((x["besok"] > 0).mean() * 100, 1), "t": round(s.mean() / (s.std() / np.sqrt(len(s))), 1),
                     "trade3%": round(x["hasil"].mean() * 100, 2)})
    q = pd.qcut(v["ps_kuat_saat_merah"].rank(method="first"), 5, labels=["1 lemah", "2", "3", "4", "5 kuat"])
    for lab, x in v.groupby(q, observed=True):
        s = x["selisih"]
        rows.append({"ciri": f"Kekuatan saat IHSG merah: kelompok {lab}", "n": len(x), "besok%": round(x["besok"].mean() * 100, 3),
                     "selisih%": round(s.mean() * 100, 3), "naik%": round((x["besok"] > 0).mean() * 100, 1),
                     "t": round(s.mean() / (s.std() / np.sqrt(len(s))), 1), "trade3%": round(x["hasil"].mean() * 100, 2)})
    print(pd.DataFrame(rows).to_string(index=False))

    # ---- 2. model B dengan ciri psikologi (walk-forward)
    from sklearn.ensemble import HistGradientBoostingRegressor
    basis = list(d.attrs["ciri"])
    dengan = basis + kol
    lat = d[d["layak"] & d["hasil"].notna()].copy()
    lat["pk_hasil"] = lat.groupby("t")["hasil"].rank(pct=True)
    tgl = np.array(sorted(d["t"].unique()))
    u["sb"], u["sp"] = np.nan, np.nan
    for qq in pd.period_range(u["t"].min(), u["t"].max(), freq="Q"):
        ia = np.searchsorted(tgl, np.datetime64(qq.start_time))
        tr = lat[lat["t"] < tgl[max(0, ia - 5)]]
        te = u[(u["t"] >= qq.start_time) & (u["t"] <= qq.end_time)]
        if te.empty or len(tr) < 20000:
            continue
        for kk, cr in (("sb", basis), ("sp", dengan)):
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_depth=5, min_samples_leaf=300,
                                              l2_regularization=1.0, random_state=0).fit(tr[cr], tr["pk_hasil"])
            u.loc[te.index, kk] = m.predict(te[cr])
    print(f"\nModel selesai ({time.time() - t0:.0f} dtk); ciri dasar {len(basis)}, + psikologi {len(dengan)}")
    naik = u[(u["ihsg_ma20"] > 0) & (u["r20"] <= 1.0)].dropna(subset=["sb", "sp"]).copy()
    g = naik.groupby("t")
    naik["mixb"] = g["r20"].rank(pct=True) + g["sb"].rank(pct=True)
    naik["mixp"] = g["r20"].rank(pct=True) + g["sp"].rank(pct=True)

    def top(df, kolom, n=3):
        x = df.sort_values(kolom, ascending=False).groupby("t").head(n).copy()
        x["urutan"] = x.groupby("t").cumcount() + 1
        return x
    bersih = naik[(naik["ps_euforia"] == 0) & (naik["ps_klimaks_vol"] == 0) & (naik["ps_tolak_atas"] == 0) & (naik["ps_gap_jebakan"] == 0)]
    S = {
        "B (dasar, setara sekarang)": top(naik, "mixb"),
        "B + ciri psikologi di model": top(naik, "mixp"),
        "B, buang euforia/klimaks/tolak atas/gap jebakan": top(bersih, "mixb"),
        "B + psikologi di model + buang sinyal buruk": top(bersih, "mixp"),
        "B, hanya yang kuat saat IHSG merah (>median)": top(naik[naik["ps_kuat_saat_merah"] > naik.groupby("t")["ps_kuat_saat_merah"].transform("median")], "mixb"),
    }
    rows = []
    for nm, p in S.items():
        for lab, kw in (("antrean, CL5%, keluar < MA10 (sekarang)", dict(masuk="antrean_tutup", maks=20, kelola="ma10")),
                        ("antrean, CL5%, jual hari-3", dict(masuk="antrean_tutup"))):
            r = r4.baris_hasil(f"{nm} | {lab}", r4.jalankan_set(H, p, **kw))
            rows.append(r)
    print("\n=== 2. STRATEGI B DENGAN PSIKOLOGI PASAR ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nSelesai {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    main()
