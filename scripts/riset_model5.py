"""Riset putaran 5: swing trading dengan fundamental kuat (pegang 2-8 minggu, batas rugi -8%).

Fundamental diambil dari laporan TAHUNAN Yahoo (4-5 tahun terakhir) dan dihitung PER TAHUN BUKU:
Piotroski F-Score, ROE, laba bersih tumbuh, pendapatan tumbuh, utang/ekuitas. Agar tidak memakai
informasi yang belum terbit, skor tahun buku X baru dianggap diketahui 120 hari setelah tanggal tutup buku.

Masuk  : antrean beli di harga penutupan (terisi bila harga besok turun ke sana).
Keluar : batas rugi -8%, atau penutupan di bawah MA50/MA20 (dijual di pembukaan berikutnya), maks 40 hari bursa.
Semesta: 250 saham ternilai tertinggi tahun sebelumnya (bebas bias), uji Mei 2024 s.d. data terakhir.
Catatan: Yahoo hanya memuat saham yang masih tercatat (bias saham bertahan).
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fundamental as fd  # noqa: E402
import riset_model4 as r4  # noqa: E402

MULAI = "2024-05-01"
NI = ["Net Income Common Stockholders", "Net Income"]
EQ = ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]
REV = ["Total Revenue", "Operating Revenue"]
DEBT = ["Total Debt"]


def fund_satu(kode: str) -> list[dict]:
    import yfinance as yf
    for coba in range(3):
        try:
            t = yf.Ticker(kode + ".JK")
            inc, bs, cf = t.income_stmt, t.balance_sheet, t.cashflow
            break
        except Exception:  # noqa: BLE001
            time.sleep(2 + coba * 3)
    else:
        return []
    if inc is None or bs is None or inc.empty or bs.empty:
        return []
    keu = False
    out = []
    kol = list(inc.columns)
    for k, tgl in enumerate(kol):
        try:
            bs_k = bs.loc[:, [c for c in bs.columns if c <= tgl]]
            cf_k = cf.loc[:, [c for c in cf.columns if c <= tgl]] if cf is not None and not cf.empty else cf
            inc_k = inc.iloc[:, k:]
            if bs_k.empty:
                continue
            sk = fd.hitung_skor(inc_k, bs_k, cf_k, keuangan=keu)
            ni0, ni1 = fd._ambil(inc_k, NI, 0), fd._ambil(inc_k, NI, 1)
            eq0 = fd._ambil(bs_k, EQ, 0)
            rv0, rv1 = fd._ambil(inc_k, REV, 0), fd._ambil(inc_k, REV, 1)
            debt = fd._ambil(bs_k, DEBT, 0)
            out.append({
                "kode": kode, "tutup_buku": pd.Timestamp(tgl), "tersedia": pd.Timestamp(tgl) + pd.Timedelta(days=120),
                "f_skor": sk["piotroski"], "f_terdata": sk["piotroski_terdata"],
                "roe": ni0 / eq0 if ni0 is not None and eq0 and eq0 > 0 else None,
                "laba_pos": None if ni0 is None else ni0 > 0,
                "laba_naik": None if ni0 is None or ni1 is None else ni0 > ni1,
                "pend_naik": None if rv0 is None or rv1 is None else rv0 > rv1,
                "der": debt / eq0 if debt is not None and eq0 and eq0 > 0 else None,
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def slot(tr: pd.DataFrame, K: int):
    """K slot modal, satu saham tidak dipegang dua kali bersamaan."""
    tr = tr[tr["terisi"]].sort_values(["t", "urutan"])
    if tr.empty:
        return {}
    bebas = [(pd.Timestamp("1900-01-01"), None)] * K
    modal = [1.0 / K] * K
    kej = []
    for t, kel, r, kode in zip(tr["t"], tr["keluar"], tr["hasil"], tr["kode"]):
        if any(b[1] == kode and b[0] >= t for b in bebas):
            continue
        for s in range(K):
            if bebas[s][0] < t:
                modal[s] *= 1 + r
                bebas[s] = (pd.Timestamp(kel), kode)
                kej.append((pd.Timestamp(kel), sum(modal), r))
                break
    kv = pd.Series([v for _, v, _ in kej], index=[k for k, _, _ in kej]).sort_index().groupby(level=0).last()
    dd = (kv / kv.cummax() - 1).min()
    th = kv.groupby(kv.index.year).last()
    awal = pd.concat([pd.Series([1.0]), th]).shift(1).iloc[1:]
    awal.index = th.index
    rr = np.array([x for _, _, x in kej]) * 100
    return {"porto%": round((kv.iloc[-1] - 1) * 100, 1), "dd%": round(dd * 100, 1), "trx": len(kej),
            "rata_trx%": round(rr.mean(), 2), "menang%": round((rr > 0).mean() * 100, 0),
            **{f"{y}%": round((th[y] / awal[y] - 1) * 100, 1) for y in th.index}}


def main():
    d, u, SET, H, acak, t0 = r4.siapkan(cetak_pola=False)
    kode = sorted(d["kode"].unique())
    print(f"Mengambil laporan tahunan {len(kode)} saham...")
    with ThreadPoolExecutor(6) as ex:
        baris = [x for lst in ex.map(fund_satu, kode) for x in lst]
    F = pd.DataFrame(baris)
    F["tersedia"] = pd.to_datetime(F["tersedia"]).dt.tz_localize(None)
    F = F.sort_values("tersedia")
    print(f"Fundamental: {len(F)} tahun buku dari {F['kode'].nunique()} saham ({time.time() - t0:.0f} dtk)")
    print("Sebaran tersedia:", F["tersedia"].dt.year.value_counts().sort_index().to_dict())

    x = d[d["layak"] & d["di_semesta"] & (d["t"] >= MULAI)].copy().sort_values("t")
    F["tersedia"] = F["tersedia"].astype(x["t"].dtype)
    x = pd.merge_asof(x, F.drop(columns=["tutup_buku"]), left_on="t", right_on="tersedia", by="kode", direction="backward")
    x["tren"] = (x["ma50"] > 0) & (x["ma20"] < x["ma50"]) & (x["kem50"] > 0)
    x["naik_ihsg"] = x["ihsg_ma20"] > 0
    ada = x["f_skor"].notna()
    print(f"Baris uji: {len(x):,}; dengan fundamental: {ada.mean() * 100:.0f}%")

    kuat6 = ada & (x["f_skor"] >= 6) & (x["roe"] >= 0.10) & (x["laba_pos"] == True)  # noqa: E712
    kuat7 = ada & (x["f_skor"] >= 7) & (x["roe"] >= 0.10) & (x["laba_pos"] == True)  # noqa: E712
    tumbuh = kuat6 & (x["laba_naik"] == True) & ((x["der"].isna()) | (x["der"] <= 1.5))  # noqa: E712
    lemah = ada & ((x["f_skor"] <= 3) | (x["laba_pos"] == False))  # noqa: E712
    dekat20 = (x["ma20"].abs() <= 0.03)

    def top(df, kol, n=3):
        y = df[df["r20"] <= 1.0].sort_values(kol, ascending=False).groupby("t").head(n).copy()
        y["urutan"] = y.groupby("t").cumcount() + 1
        return y

    SET5 = {
        "Tren saja (tanpa fundamental), r60": top(x[x["tren"]], "r60"),
        "Tren + F>=6 ROE>=10%, r60": top(x[x["tren"] & kuat6], "r60"),
        "Tren + F>=7 ROE>=10%, r60": top(x[x["tren"] & kuat7], "r60"),
        "Tren + F>=6 ROE>=10% laba naik DER<=1,5, r60": top(x[x["tren"] & tumbuh], "r60"),
        "Tren + F>=6 ROE>=10%, dekat MA20 (pullback), r60": top(x[x["tren"] & kuat6 & dekat20], "r60"),
        "Tren + F>=6 ROE>=10%, urut ROE": top(x[x["tren"] & kuat6], "roe"),
        "Tren + fundamental LEMAH (pembanding)": top(x[x["tren"] & lemah], "r60"),
        "F>=7 ROE>=10% tanpa syarat tren, urut ROE": top(x[kuat7], "roe"),
    }
    rows = []
    for nm, p in SET5.items():
        for ih in (False, True):
            pp = p[p["naik_ihsg"]] if ih else p
            for kel in ("ma50", "ma20", "tidak"):
                maks = 40
                for K in (3, 5):
                    tr = r4.jalankan_set(H, pp, masuk="antrean_tutup", stop="8%", maks=maks, kelola=kel)
                    if tr.empty:
                        continue
                    isi = tr[tr["terisi"]]
                    rows.append({"strategi": nm, "IHSG>MA20": "ya" if ih else "-", "keluar": kel if kel != "tidak" else "hari-40",
                                 "K": K, "sinyal": len(isi), "hari_pegang": round(isi["hari"].mean(), 1), **slot(tr, K)})
    pd.set_option("display.width", 320)
    pd.set_option("display.max_rows", 400)
    R = pd.DataFrame(rows)
    print("\n=== SWING FUNDAMENTAL: SEMUA VARIASI (portofolio K slot, satu saham sekali pegang) ===")
    print(R.to_string(index=False))
    print("\n=== 15 TERBAIK (K=3, minimal 30 transaksi) ===")
    print(R[(R["K"] == 3) & (R["trx"] >= 30)].sort_values("porto%", ascending=False).head(15).to_string(index=False))
    print("\nPembanding: IHSG", round((x.groupby("t")["ihsg_r1"].first().add(1).prod() - 1) * 100, 1), "% pada periode uji")
    print(f"\nSelesai {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    main()
