"""Riset 7: uji mundur aturan "Saham potensial" (maks 10, baru/bertahan/keluar) seperti di web.

Skor = peringkat(kenaikan 20 hari) + peringkat(model B walk-forward), hanya saham layak dengan kenaikan 20 hari <= 100%.
Masuk bila peringkat <= 8 dan harga di atas MA20; bertahan selama peringkat <= 20 dan di atas MA20; maks 10.
Dinilai seperti di web: perubahan penutupan besok (naik/turun), dibanding rata-rata semua saham layak hari itu
(unggul pasar), serta perubahan 3 dan 5 hari bursa. Periode 2024 s.d. data terakhir, semesta bebas bias.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import riset_model4 as r4  # noqa: E402

pd.set_option("display.width", 250)


def main():
    d, u, SET, H, acak, t0 = r4.siapkan(cetak_pola=False)
    d = d.sort_values(["kode", "t"])
    g = d.groupby("kode")
    for h in (3, 5):
        d[f"r{h}d"] = g["tutup"].shift(-h) / d["tutup"] - 1
    u = u.join(d[["r3d", "r5d"]])
    x = u.dropna(subset=["s0"]).copy()
    x = x[x["r20"] <= 1.0]
    gt = x.groupby("t")
    x["skor"] = gt["r20"].rank(pct=True) + gt["s0"].rank(pct=True)
    x["peringkat"] = x.groupby("t")["skor"].rank(ascending=False, method="first")
    for k in ("besok", "r3d", "r5d"):
        x[f"ex_{k}"] = x[k] - x.groupby("t")[k].transform("mean")

    daftar_rows, kemarin = [], {}
    for t, hari in x.groupby("t", sort=True):
        info = hari.set_index("kode")
        baru = {}
        for k, sejak in kemarin.items():
            if k in info.index and info.at[k, "peringkat"] <= 20 and info.at[k, "ma20"] >= 0:
                baru[k] = ("bertahan", sejak)
        for k, r in info[(info["peringkat"] <= 8) & (info["ma20"] >= 0)].iterrows():
            baru.setdefault(k, ("baru", t))
        urut = sorted(baru, key=lambda k: info.at[k, "peringkat"])[:10]
        for k in urut:
            r = info.loc[k]
            daftar_rows.append({"t": t, "kode": k, "status": baru[k][0], "peringkat": r["peringkat"],
                                "besok": r["besok"], "r3d": r["r3d"], "r5d": r["r5d"],
                                "ex_besok": r["ex_besok"], "ex_r3d": r["ex_r3d"], "ex_r5d": r["ex_r5d"],
                                "ihsg_naik": r["ihsg_ma20"] > 0})
        kemarin = {k: baru[k][1] for k in urut}
    L = pd.DataFrame(daftar_rows).dropna(subset=["besok"])

    def ring(df, nama):
        if len(df) < 20:
            return {"kelompok": nama, "n": len(df)}
        return {"kelompok": nama, "n": len(df), "hari": df["t"].nunique(), "saham/hari": round(len(df) / df["t"].nunique(), 1),
                "naik_besok%": round((df["besok"] > 0).mean() * 100, 1), "turun_besok%": round((df["besok"] < 0).mean() * 100, 1),
                "unggul_pasar_besok%": round((df["ex_besok"] > 0).mean() * 100, 1),
                "rata_besok%": round(df["besok"].mean() * 100, 2), "selisih_pasar_besok%": round(df["ex_besok"].mean() * 100, 2),
                "rata_3h%": round(df["r3d"].mean() * 100, 2), "selisih_3h%": round(df["ex_r3d"].mean() * 100, 2),
                "rata_5h%": round(df["r5d"].mean() * 100, 2), "selisih_5h%": round(df["ex_r5d"].mean() * 100, 2)}

    rows = [ring(L, "SEMUA daftar potensial"), ring(L[L["status"] == "baru"], "baru masuk"),
            ring(L[L["status"] == "bertahan"], "bertahan"),
            ring(L[L["peringkat"] <= 3], "peringkat 1-3"), ring(L[(L["peringkat"] > 3) & (L["peringkat"] <= 10)], "peringkat 4-10"),
            ring(L[L["peringkat"] > 10], "peringkat 11-20 (bertahan)"),
            ring(L[L["ihsg_naik"]], "saat IHSG > MA20"), ring(L[~L["ihsg_naik"]], "saat IHSG < MA20")]
    for y, gy in L.groupby(pd.to_datetime(L["t"]).dt.year):
        rows.append(ring(gy, f"tahun {y}"))
    pemb = x.dropna(subset=["besok"])
    rows.append(ring(pemb.assign(ex_besok=pemb["ex_besok"], status="-"), "PEMBANDING: semua saham layak"))
    print("\n=== UJI MUNDUR DAFTAR SAHAM POTENSIAL (2024 s.d. sekarang) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    # kestabilan daftar
    per_hari = L.groupby("t").size()
    baru_hari = L[L["status"] == "baru"].groupby("t").size().reindex(per_hari.index, fill_value=0)
    print(f"\nRata-rata isi daftar {per_hari.mean():.1f} saham/hari (min {per_hari.min()}, maks {per_hari.max()}); "
          f"rata-rata {baru_hari.mean():.1f} saham baru per hari")
    # akurasi harian: berapa persen hari yang mayoritas daftar unggul pasar
    hh = L.groupby("t").agg(unggul=("ex_besok", lambda s: (s > 0).mean()), rata=("ex_besok", "mean"))
    print(f"Hari ketika >= separuh daftar unggul pasar besok: {(hh['unggul'] >= 0.5).mean() * 100:.1f}% dari {len(hh)} hari; "
          f"hari ketika rata-rata daftar unggul pasar: {(hh['rata'] > 0).mean() * 100:.1f}%")
    s = L["ex_besok"]
    print(f"t-stat selisih pasar besok (per saham): {s.mean() / (s.std() / np.sqrt(len(s))):.2f}; "
          f"per hari: {hh['rata'].mean() / (hh['rata'].std() / np.sqrt(len(hh))):.2f}")


if __name__ == "__main__":
    main()
