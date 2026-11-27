"""Riset 4b: ketahanan aturan keluar "biarkan untung berjalan" (jual bila tutup di bawah MA).

Semua: masuk dengan antrean di harga penutupan, batas rugi 5%, IHSG > MA20.
Variasi: MA5 / MA10 / MA20 / MA10 dua hari berturut-turut, lama pegang maksimal 20 atau 40 hari,
dan ketergantungan pada sedikit transaksi besar (porsi 5% transaksi terbaik).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import riset_model4 as r4  # noqa: E402
from riset_model2 import ringkas  # noqa: E402


def main():
    d, u, SET, H, acak, t0 = r4.siapkan(cetak_pola=False)
    rows, tahunan = [], []
    for nm in ("B (sekarang)", "A momentum tanpa distribusi"):
        for kel in ("tidak", "ma5", "ma10", "ma10x2", "ma20"):
            for maks in ((3,) if kel == "tidak" else (20, 40)):
                lab = f"{nm} | keluar {kel if kel != 'tidak' else 'hari-3'} | maks {maks}h"
                tr = r4.jalankan_set(H, SET[nm], masuk="antrean_tutup", maks=maks, kelola=kel)
                r = r4.baris_hasil(lab, tr)
                isi = tr[tr["terisi"]]
                r["porsi_top5%"] = ringkas(isi["hasil"]).get("porsi_top5%")
                r["rata_tanpa_top5%"] = round(isi["hasil"].sort_values().iloc[: int(len(isi) * 0.95)].mean() * 100, 3)
                rows.append(r)
                for y, g in isi.groupby(pd.to_datetime(isi["t"]).dt.to_period("Q")):
                    tahunan.append({"strategi": lab, "kuartal": str(y), "rata%": round(g["hasil"].mean() * 100, 2)})
        # 5 pilihan per hari (utama + cadangan) dengan MA10
        lab = f"{nm} | keluar ma10 | maks 20h | 5 slot"
        tr = r4.jalankan_set(H, SET[nm], masuk="antrean_tutup", maks=20, kelola="ma10")
        r = r4.baris_hasil(lab, tr)
        r.update(r4.portofolio_slot(tr, K=5))
        rows.append(r)
    rows.append(r4.baris_hasil("acak | keluar ma10 | maks 20h",
                               r4.jalankan_set(H, acak, masuk="antrean_tutup", maks=20, kelola="ma10")))
    pd.set_option("display.width", 300)
    print("\n=== KETAHANAN ATURAN KELUAR ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nRata-rata per kuartal (%):")
    print(pd.DataFrame(tahunan).pivot_table(index="kuartal", columns="strategi", values="rata%").round(2).to_string())


if __name__ == "__main__":
    main()
