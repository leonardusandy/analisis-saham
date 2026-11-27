"""Riset putaran 4: cara trading pengguna yang sebenarnya.

1. Pola candlestick + volume: seberapa baik setiap pola menebak pergerakan BESOK
   (dibanding rata-rata semua saham pada hari yang sama), dan apakah menambah pola ke model
   memperbaiki strategi B.
2. Cara beli: antrean beli di rentang harga (bukan beli di harga pembukaan). Antrean hanya
   terisi bila harga besok turun sampai harga antrean.
3. Rasio untung:rugi 1:1, 1:2, 1:3 dengan batas rugi 5% / struktur (terendah 5 hari) / 1 ATR,
   ditambah pengelolaan posisi harian (batas rugi dinaikkan saat untung) dan lama pegang 3-20 hari.
4. Aturan pribadi pengguna (dari infografis): pantulan di akhir koreksi (gelombang 2/4,
   retracement Fibonacci 38-62%) dan breakout resistensi bervolume, dengan syarat ruang naik >= 2R.

Uji: 2024-01 s.d. data terakhir, semesta bebas bias (250 saham ternilai tertinggi tahun sebelumnya),
model walk-forward (dilatih ulang tiap kuartal). Biaya beli 0,15%, jual 0,25%.
Log hanya berisi statistik gabungan, tanpa daftar saham hari ini.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import riset_model as rm  # noqa: E402
from riset_model2 import ringkas  # noqa: E402

B, J = rm.B, rm.J
N_SEMESTA = 250
K = 3


# ---------------------------------------------------------------- 1. pola candlestick
def tambah_pola(d: pd.DataFrame) -> list[str]:
    g = d.groupby("kode", sort=False)
    o, h, l, c = d["buka"], d["tinggi"], d["rendah"], d["tutup"]
    sh = lambda s, n=1: g[s.name].shift(n)  # noqa: E731
    o1, h1, l1, c1 = sh(o), sh(h), sh(l), sh(c)
    o2, h2, l2, c2 = sh(o, 2), sh(h, 2), sh(l, 2), sh(c, 2)
    rng = (h - l).replace(0, np.nan)
    rng1, rng2 = (h1 - l1).replace(0, np.nan), (h2 - l2).replace(0, np.nan)
    badan, badan1, badan2 = (c - o).abs(), (c1 - o1).abs(), (c2 - o2).abs()
    sa, sb = h - np.maximum(o, c), np.minimum(o, c) - l
    hijau, merah = c > o, c < o
    hijau1, merah1, hijau2, merah2 = c1 > o1, c1 < o1, c2 > o2, c2 < o2
    c6 = sh(c, 6)
    turun_dulu, naik_dulu = c1 < c6 * 0.97, c1 > c6 * 1.03
    besar = rng / c >= 0.02
    ma20 = c / (1 + d["ma20"])
    tren = (d["ma50"] > 0) & (d["ma20"] < d["ma50"]) & (d["kem50"] > 0)
    hi20p = g["tinggi"].transform(lambda x: x.shift(1).rolling(20).max())
    lo20p = g["rendah"].transform(lambda x: x.shift(1).rolling(20).min())
    palu = (sb >= 0.6 * rng) & (sa <= 0.15 * rng) & (badan <= 0.35 * rng) & besar
    bintang = (sa >= 0.6 * rng) & (sb <= 0.15 * rng) & (badan <= 0.35 * rng) & besar
    turun3 = (c < c1) & (c1 < c2) & (c2 < sh(c, 3))
    vol3 = g["rv1"].transform(lambda x: x.rolling(3).mean())
    rv = d["rv1"]
    pola = {
        "Doji": (badan <= 0.1 * rng) & besar,
        "Palu (hammer) setelah turun": palu & turun_dulu,
        "Palu di MA20 saat tren naik": palu & tren & (l <= ma20) & (c >= ma20),
        "Hanging man setelah naik": palu & naik_dulu,
        "Bintang jatuh (shooting star) setelah naik": bintang & naik_dulu,
        "Palu terbalik setelah turun": bintang & turun_dulu,
        "Bullish engulfing": merah1 & hijau & (o <= c1) & (c >= o1) & (badan > badan1),
        "Bullish engulfing setelah turun": merah1 & hijau & (o <= c1) & (c >= o1) & (badan > badan1) & turun_dulu,
        "Bearish engulfing": hijau1 & merah & (o >= c1) & (c <= o1) & (badan > badan1),
        "Bearish engulfing setelah naik": hijau1 & merah & (o >= c1) & (c <= o1) & (badan > badan1) & naik_dulu,
        "Piercing line": merah1 & (badan1 >= 0.6 * rng1) & hijau & (o <= c1) & (c > (o1 + c1) / 2) & (c < o1),
        "Dark cloud cover": hijau1 & (badan1 >= 0.6 * rng1) & merah & (o >= c1) & (c < (o1 + c1) / 2) & (c > o1),
        "Morning star": merah2 & (badan2 >= 0.5 * rng2) & (badan1 <= 0.3 * rng1) & hijau & (c > (o2 + c2) / 2),
        "Evening star": hijau2 & (badan2 >= 0.5 * rng2) & (badan1 <= 0.3 * rng1) & merah & (c < (o2 + c2) / 2),
        "Three white soldiers": hijau & hijau1 & hijau2 & (c > c1) & (c1 > c2)
                                & ((c - l) >= 0.7 * rng) & ((c1 - l1) >= 0.7 * rng1),
        "Three black crows": merah & merah1 & merah2 & (c < c1) & (c1 < c2)
                             & ((h - c) >= 0.7 * rng) & ((h1 - c1) >= 0.7 * rng1),
        "Inside bar": (h < h1) & (l > l1),
        "Marubozu hijau": hijau & (badan >= 0.85 * rng) & besar,
        "Marubozu merah": merah & (badan >= 0.85 * rng) & besar,
        "Gap naik": o > h1,
        "Gap turun": o < l1,
        "Tutup di harga tertinggi (hijau)": hijau & ((c - l) >= 0.9 * rng) & besar,
        "Breakout 20 hari + volume >=1,5x": (c > hi20p) & (rv >= 1.5),
        "Breakout 20 hari tanpa volume (<1x)": (c > hi20p) & (rv < 1.0),
        "Breakdown 20 hari + volume >=1,5x": (c < lo20p) & (rv >= 1.5),
        "Hijau bervolume >=2x": hijau & (rv >= 2) & besar,
        "Merah bervolume >=2x (distribusi)": merah & (rv >= 2) & besar,
        "Tren naik, volume mengering (<0,5x)": tren & (rv < 0.5),
        "Tren naik, turun 3 hari volume kecil": tren & turun3 & (vol3 < 0.8),
        "Tren naik, turun 3 hari volume besar": tren & turun3 & (vol3 >= 1.5),
    }
    nama = []
    for i, (k, v) in enumerate(pola.items()):
        kol = f"pola_{i:02d}"
        d[kol] = v.fillna(False).astype(float)
        nama.append((kol, k))
    d["_hi20p"], d["_lo5"] = hi20p, g["rendah"].transform(lambda x: x.rolling(5).min())
    d["_hi60p"] = g["tinggi"].transform(lambda x: x.shift(1).rolling(60).max())
    d["_tren"] = tren
    d["_h1"] = h1
    return nama


def statistik_pola(u: pd.DataFrame, nama):
    print("\n=== 1. POLA CANDLESTICK + VOLUME: APA YANG TERJADI BESOK? ===")
    print("Besok% = rata-rata perubahan harga penutupan besok. Selisih% = dibanding rata-rata semua saham hari itu.")
    print("Naik% = seberapa sering harga besok naik. t = kekuatan bukti (|t| >= 2 berarti cukup meyakinkan).")
    print("Trade3% = hasil bersih bila dibeli besok pagi dan dijual hari ke-3 (cara lama).")
    rows = [{"pola": "(semua saham, pembanding)", "n": len(u), "besok%": round(u["besok"].mean() * 100, 3),
             "selisih%": 0.0, "naik%": round((u["besok"] > 0).mean() * 100, 1), "t": None,
             "trade3%": round(u["hasil"].mean() * 100, 2)}]
    for kol, k in nama:
        x = u[u[kol] == 1]
        if len(x) < 30:
            rows.append({"pola": k, "n": len(x)})
            continue
        s = x["selisih"]
        rows.append({"pola": k, "n": len(x), "besok%": round(x["besok"].mean() * 100, 3),
                     "selisih%": round(s.mean() * 100, 3), "naik%": round((x["besok"] > 0).mean() * 100, 1),
                     "t": round(s.mean() / (s.std() / np.sqrt(len(s))), 1), "trade3%": round(x["hasil"].mean() * 100, 2)})
    print(pd.DataFrame(rows).to_string(index=False))


# ---------------------------------------------------------------- 2-3. simulasi transaksi
class Harga:
    def __init__(self, d):
        self.arr = {}
        for k, g in d.groupby("kode", sort=False):
            self.arr[k] = {c: g[c].to_numpy(dtype=float) for c in
                           ("buka", "tinggi", "rendah", "tutup", "atr_rp", "_lo5", "_hi60p", "_hi20p", "ma5_rp", "ma10_rp",
                            "ma20_rp", "ma50_rp") if c in g}
            self.arr[k]["t"] = g["t"].to_numpy()


def simulasi(a, i, masuk="buka", stop="5%", r_target=None, maks=3, kelola="tidak", syarat_ruang=None):
    """Satu transaksi dari sinyal di hari i. Kembalikan (hasil bersih, hari dipegang, terisi?, t_keluar)."""
    o, h, l, c, atr = a["buka"], a["tinggi"], a["rendah"], a["tutup"], a["atr_rp"]
    n = len(c)
    if i + 1 >= n or not (atr[i] > 0):
        return None
    ara = rm.batas_ara(np.array([c[i]]))[0]
    # --- harga antrean / beli
    if masuk == "buka":
        e = o[i + 1]
        if not e > 0 or e >= c[i] * (1 + ara) * 0.995:
            return (np.nan, 0, False, None)
    else:
        lim = c[i] if masuk == "antrean_tutup" else c[i] - (0.5 if masuk == "antrean_0,5atr" else 0.25) * atr[i]
        if not l[i + 1] <= lim:
            return (np.nan, 0, False, None)  # antrean tidak terisi
        e = min(o[i + 1], lim)
    # --- batas rugi
    if stop.endswith("%"):
        s = e * (1 - float(stop[:-1]) / 100)
    elif stop == "1atr":
        s = e - atr[i]
    else:  # struktur: di bawah harga terendah 5 hari, risiko dibatasi 1,5%..5%
        s = min(a["_lo5"][i], e) * 0.99
        s = min(max(s, e * 0.95), e * 0.985)
    risiko = e - s
    tp = e + r_target * risiko if r_target else None
    if syarat_ruang:
        res = a["_hi60p"][i]
        if not (c[i] >= res * 0.98 or (res - e) >= syarat_ruang * risiko):
            return (np.nan, 0, False, None)
    # --- jalannya posisi
    j0 = i + 1
    keluar, hari_keluar = None, None
    tertinggi = e
    sisa, terkunci = 1.0, 0.0  # untuk ambil untung bertahap
    for j in range(j0, min(n, j0 + maks)):
        if j > j0 and o[j] <= s:
            keluar, hari_keluar = o[j], j
            break
        if l[j] <= s and (j > j0 or masuk == "buka" or l[j] < min(o[j], e)):
            keluar, hari_keluar = s, j
            break
        if tp is not None and j > j0:
            if kelola == "bertahap" and sisa == 1.0:
                tp1 = e + 1.5 * risiko
                if h[j] >= tp1:
                    terkunci += 0.5 * (max(o[j], tp1) * (1 - J) / (e * (1 + B)) - 1)
                    sisa = 0.5
                    s = max(s, e * 1.005)
            if o[j] >= tp:
                keluar, hari_keluar = o[j], j
                break
            if h[j] >= tp:
                keluar, hari_keluar = tp, j
                break
        # pembaruan harian setelah penutupan
        tertinggi = max(tertinggi, c[j])
        if kelola in ("ikut", "bertahap"):
            if c[j] >= e + risiko:
                s = max(s, e * 1.005)          # impas setelah untung 1R
            if c[j] >= e + 2 * risiko:
                s = max(s, e + risiko)         # kunci 1R setelah untung 2R
            if c[j] >= e + 2 * risiko:
                s = max(s, tertinggi - 2 * atr[i])
        elif kelola.startswith("ma"):
            mak = a[kelola.split("x")[0] + "_rp"]
            dua = kelola.endswith("x2")
            bawah = c[j] < mak[j] and (not dua or (j - 1 >= j0 and c[j - 1] < mak[j - 1]))
            if bawah and j > j0:
                keluar, hari_keluar = (o[j + 1] if j + 1 < n else c[j]), min(j + 1, n - 1)
                break
    if keluar is None:
        jj = min(n - 1, j0 + maks - 1)
        if j0 + maks - 1 >= n:
            return None  # belum selesai
        keluar, hari_keluar = c[jj], jj
    hasil = sisa * (keluar * (1 - J) / (e * (1 + B)) - 1) + terkunci
    return (hasil, hari_keluar - i, True, a["t"][hari_keluar])


def jalankan_set(H: Harga, pil: pd.DataFrame, **kw):
    out = []
    for kode, pos, t, urut in zip(pil["kode"], pil["pos"], pil["t"], pil["urutan"]):
        r = simulasi(H.arr[kode], int(pos), **kw)
        if r is None:
            continue
        out.append({"t": t, "kode": kode, "urutan": urut, "hasil": r[0], "hari": r[1], "terisi": r[2], "keluar": r[3]})
    return pd.DataFrame(out)


def portofolio_slot(tr: pd.DataFrame, K=K):
    """K slot modal; transaksi baru masuk bila ada slot kosong (sesuai urutan pilihan)."""
    tr = tr[tr["terisi"]].sort_values(["t", "urutan"])
    if tr.empty:
        return {}
    bebas = [pd.Timestamp("1900-01-01")] * K
    modal = [1.0 / K] * K
    kejadian = []
    for t, kel, r in zip(tr["t"], tr["keluar"], tr["hasil"]):
        for s in range(K):
            if bebas[s] < t:
                modal[s] *= 1 + r
                bebas[s] = pd.Timestamp(kel)
                kejadian.append((pd.Timestamp(kel), sum(modal)))
                break
    kv = pd.Series([v for _, v in kejadian], index=[k for k, _ in kejadian]).sort_index()
    kv = kv.groupby(level=0).last()
    dd = (kv / kv.cummax() - 1).min()
    th = kv.groupby(kv.index.year).last()
    awal = pd.concat([pd.Series([1.0]), th]).shift(1).iloc[1:]
    awal.index = th.index
    return {"total%": round((kv.iloc[-1] - 1) * 100, 1), "drawdown%": round(dd * 100, 1),
            "transaksi_dijalankan": len(kejadian),
            **{f"thn{y}%": round((th[y] / awal[y] - 1) * 100, 1) for y in th.index}}


def baris_hasil(nama, tr):
    if tr.empty:
        return {"strategi": nama}
    isi = tr[tr["terisi"]]
    r = ringkas(isi["hasil"], nama)
    m, k = isi.loc[isi["hasil"] > 0, "hasil"], isi.loc[isi["hasil"] <= 0, "hasil"]
    r.update({"terisi%": round(tr["terisi"].mean() * 100, 0), "hari_pegang": round(isi["hari"].mean(), 1),
              "rata_untung%": round(m.mean() * 100, 2) if len(m) else None,
              "rata_rugi%": round(k.mean() * 100, 2) if len(k) else None})
    r.pop("rata_batas30%", None)
    r.pop("porsi_top5%", None)
    r.update(portofolio_slot(tr))
    return r


# ---------------------------------------------------------------- utama
def siapkan(cetak_pola=True):
    d, CIRI, _, t0 = rm.bangun_data(pakai_global=False)
    d = d.sort_values(["kode", "t"]).reset_index(drop=True)
    d["pos"] = d.groupby("kode").cumcount()
    d["atr_rp"] = d["atr"] * d["tutup"]
    for m in (5, 10, 20, 50):
        d[f"ma{m}_rp"] = d["tutup"] / (1 + d[f"ma{m}"])
    nama_pola = tambah_pola(d)
    d["besok"] = d.groupby("kode")["tutup"].shift(-1) / d["tutup"] - 1
    d["tahun"] = d["t"].dt.year
    d["nilai_rp"] = np.expm1(d["nilai"])
    print(f"Data siap ({time.time() - t0:.0f} dtk), {len(d):,} baris")

    # semesta bebas bias
    st = d.groupby(["tahun", "kode"]).agg(nilai=("nilai_rp", "mean"), harga=("tutup", "mean")).reset_index()
    semesta = {y: set(st[(st["tahun"] == y - 1) & (st["harga"] >= 100)].nlargest(N_SEMESTA, "nilai")["kode"])
               for y in (2022, 2023, 2024, 2025, 2026)}
    d["di_semesta"] = [k in semesta.get(y, set()) for k, y in zip(d["kode"], d["tahun"])]

    # ---- 1. pola (seluruh 5 tahun & periode uji)
    v = d[d["layak"] & d["besok"].notna() & d["hasil"].notna() & d["di_semesta"]].copy()
    v["selisih"] = v["besok"] - v.groupby("t")["besok"].transform("mean")
    if cetak_pola:
        statistik_pola(v, nama_pola)
        print("\n-- Sama, hanya periode uji 2024 s.d. sekarang --")
        statistik_pola(v[v["t"] >= rm.MULAI_UJI], nama_pola)

    # ---- model peringkat walk-forward: tanpa dan dengan ciri pola
    from sklearn.ensemble import HistGradientBoostingRegressor
    ciri = [c for c in CIRI if not c.startswith(("ihsg_", "luas_", "g_")) and c != "hari"]
    ciri_pola = ciri + [k for k, _ in nama_pola]
    lat = d[d["layak"] & d["hasil"].notna()].copy()
    lat["pk_hasil"] = lat.groupby("t")["hasil"].rank(pct=True)
    u = d[d["layak"] & d["hasil"].notna() & (d["t"] >= rm.MULAI_UJI) & d["di_semesta"]].copy()
    tgl = np.array(sorted(d["t"].unique()))
    u["s0"], u["s1"] = np.nan, np.nan
    for q in pd.period_range(u["t"].min(), u["t"].max(), freq="Q"):
        ia = np.searchsorted(tgl, np.datetime64(q.start_time))
        tr = lat[lat["t"] < tgl[max(0, ia - 5)]]
        te = u[(u["t"] >= q.start_time) & (u["t"] <= q.end_time)]
        if te.empty or len(tr) < 20000:
            continue
        for kol, cr in (("s0", ciri), ("s1", ciri_pola)):
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_depth=5, min_samples_leaf=300,
                                              l2_regularization=1.0, random_state=0).fit(tr[cr], tr["pk_hasil"])
            u.loc[te.index, kol] = m.predict(te[cr])
    print(f"\nModel walk-forward selesai ({time.time() - t0:.0f} dtk)")

    naik = u[(u["ihsg_ma20"] > 0) & (u["r20"] <= 1.0)].dropna(subset=["s0"]).copy()
    g = naik.groupby("t")

    def top(df, kol, n=K):
        x = df.sort_values(kol, ascending=False).groupby("t").head(n).copy()
        x["urutan"] = x.groupby("t").cumcount() + 1
        return x

    naik["mixB"] = g["r20"].rank(pct=True) + g["s0"].rank(pct=True)
    naik["mixBp"] = g["r20"].rank(pct=True) + g["s1"].rank(pct=True)
    tren = naik["_tren"].astype(bool)
    pant = naik[tren & naik["pos20"].between(0.25, 0.65) & (naik["tutup"] > naik["_h1"])
                & (naik["tutup"] > naik["buka"]) & (naik["rv1"] >= 1.0) & naik["rsi14"].between(40, 65)
                & (naik["distribusi"] == 0)]
    bo = naik[tren & (naik["tutup"] > naik["_hi20p"]) & (naik["rv1"] >= 1.5) & (naik["tutup"] > naik["buka"])
              & (naik["pos_tutup"] >= 0.7) & (naik["r20"] <= 0.5)]
    SET = {
        "B (sekarang)": top(naik, "mixB"),
        "B + pola candlestick": top(naik, "mixBp"),
        "A momentum tanpa distribusi": top(naik[naik["distribusi"] == 0], "r20"),
        "Anda: pantulan koreksi (gel. 2/4)": top(pant, "rv1"),
        "Anda: breakout resistensi bervolume": top(bo, "rv1"),
    }
    H = Harga(d)
    acak = u[u["ihsg_ma20"] > 0].sample(n=min(6000, len(u)), random_state=0).copy()
    acak["urutan"] = 1
    return d, u, SET, H, acak, t0


def main():
    d, u, SET, H, acak, t0 = siapkan()

    print("\n=== 2. MODEL + POLA CANDLESTICK (cara lama: beli pembukaan, CL5%, jual hari-3) ===")
    rows = [baris_hasil(nm, jalankan_set(H, p)) for nm, p in SET.items()]
    rows.append(baris_hasil("acak (pembanding)", jalankan_set(H, acak)))
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== 3. CARA BELI: PEMBUKAAN vs ANTREAN (CL5%, jual hari-3) ===")
    rows = []
    for nm in ("B (sekarang)", "A momentum tanpa distribusi", "Anda: pantulan koreksi (gel. 2/4)",
               "Anda: breakout resistensi bervolume"):
        for m in ("buka", "antrean_tutup", "antrean_0,25atr", "antrean_0,5atr"):
            rows.append(baris_hasil(f"{nm} | {m}", jalankan_set(H, SET[nm], masuk=m)))
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== 4. RASIO UNTUNG:RUGI & PENGELOLAAN HARIAN (masuk: antrean di harga penutupan) ===")
    rows = []
    kombinasi = []
    for st_ in ("5%", "struktur", "1atr"):
        for rt in (None, 1, 2, 3):
            for maks in (3, 10):
                for kel in ("tidak", "ikut"):
                    kombinasi.append(dict(stop=st_, r_target=rt, maks=maks, kelola=kel))
    kombinasi += [dict(stop="struktur", r_target=3, maks=10, kelola="ikut", syarat_ruang=3),
                  dict(stop="struktur", r_target=3, maks=20, kelola="ikut"),
                  dict(stop="struktur", r_target=3, maks=20, kelola="bertahap"),
                  dict(stop="5%", r_target=3, maks=20, kelola="ikut"),
                  dict(stop="struktur", r_target=None, maks=20, kelola="ma10"),
                  dict(stop="5%", r_target=None, maks=20, kelola="ma10")]
    for nm in ("B (sekarang)", "A momentum tanpa distribusi", "Anda: pantulan koreksi (gel. 2/4)",
               "Anda: breakout resistensi bervolume"):
        for kw in kombinasi:
            lab = f"{nm} | CL {kw['stop']} | target {('%dR' % kw['r_target']) if kw['r_target'] else '-'} | " \
                  f"maks {kw['maks']}h | {kw['kelola']}" + (" | ruang>=3R" if kw.get("syarat_ruang") else "")
            rows.append(baris_hasil(lab, jalankan_set(H, SET[nm], masuk="antrean_tutup", **kw)))
    hasil = pd.DataFrame(rows)
    print(hasil.to_string(index=False))
    print("\n-- 15 kombinasi terbaik menurut portofolio (minimal 150 transaksi) --")
    print(hasil[hasil["n"] >= 150].sort_values("total%", ascending=False).head(15).to_string(index=False))
    print("\n-- Pembanding acak dengan pengelolaan 1:3 --")
    print(pd.DataFrame([
        baris_hasil("acak | CL5% hari-3", jalankan_set(H, acak, masuk="antrean_tutup")),
        baris_hasil("acak | struktur 3R maks10 ikut", jalankan_set(H, acak, masuk="antrean_tutup", stop="struktur",
                                                               r_target=3, maks=10, kelola="ikut")),
    ]).to_string(index=False))
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    main()
