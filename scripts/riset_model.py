"""Riset model prediksi untuk gaya trading 1-3 hari (dijalankan manual di GitHub Actions).

Pertanyaan: model mana yang paling baik MEMILIH saham untuk dibeli besok, bila hasilnya diukur
persis seperti cara trading pengguna?

  Transaksi : beli di harga pembukaan hari t+1, batas rugi -5% dari harga beli (bila harga dibuka
              di bawahnya, dijual di harga pembukaan), selain itu jual di penutupan hari ke-3.
              Biaya beli 0,15% dan jual 0,25% dipotong. Tidak bisa beli bila pembukaan t+1 sudah
              di batas atas (ARA).
  Semesta   : saham ramai (nilai transaksi rata-rata 20 hari >= Rp1 M), harga >= Rp50, ada volume.
  Uji       : walk-forward. Model dilatih ulang tiap kuartal hanya dengan data sebelum kuartal itu
              (jeda 5 hari bursa), lalu memilih K saham terbaik setiap hari di kuartal tersebut.
              Periode uji 2024-01 s.d. data terakhir; tidak ada data masa depan yang dipakai.
  Pembanding: aturan J, pilihan acak (rata-rata semua saham layak), momentum 20 hari.

Hasil dicetak di log (hanya statistik gabungan, tanpa daftar saham hari ini).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
import jalankan  # noqa: E402

cfg.PERIODE = "5y"
B, J = cfg.BIAYA_BELI, cfg.BIAYA_JUAL
H = 3
MULAI_UJI = "2024-01-01"
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def batas_ara(c):
    return np.where(c <= 200, 0.35, np.where(c <= 5000, 0.25, 0.20))


def hasil_transaksi(o, h, l, c, stop_pct=0.05, tp_pct=None, hari=H, atr=None, kali_atr=None):
    """Hasil bersih transaksi untuk sinyal di setiap hari t (NaN bila tidak bisa dihitung).
    Beli di pembukaan t+1; keluar bila batas rugi / ambil untung tersentuh (batas rugi dianggap
    lebih dulu bila keduanya di hari yang sama), selain itu di penutupan hari ke-`hari`."""
    n = len(c)
    out = np.full(n, np.nan)
    ara = batas_ara(c)
    for i in range(n - hari):
        e = o[i + 1]
        if not e > 0 or e >= c[i] * (1 + ara[i]) * 0.995:  # pembukaan sudah ARA: tidak bisa beli
            continue
        if kali_atr is not None:
            if not atr[i] > 0:
                continue
            stop = e - kali_atr * atr[i]
        else:
            stop = e * (1 - stop_pct) if stop_pct else -1
        tp = e * (1 + tp_pct) if tp_pct else None
        keluar = None
        for j in range(i + 1, i + 1 + hari):
            if j > i + 1 and o[j] <= stop:
                keluar = o[j]
                break
            if l[j] <= stop:
                keluar = stop
                break
            if tp is not None:
                if j > i + 1 and o[j] >= tp:
                    keluar = o[j]
                    break
                if h[j] >= tp:
                    keluar = tp
                    break
        if keluar is None:
            keluar = c[i + hari]
        out[i] = keluar * (1 - J) / (e * (1 + B)) - 1
    return out


VARIASI_KELUAR = {
    "CL5% jual hari-3 (sekarang)": {},
    "CL3% jual hari-3": {"stop_pct": 0.03},
    "CL7% jual hari-3": {"stop_pct": 0.07},
    "CL 1,5xATR jual hari-3": {"kali_atr": 1.5},
    "CL5% TP5% hari-3": {"tp_pct": 0.05},
    "CL5% TP8% hari-3": {"tp_pct": 0.08},
    "CL5% jual hari-1": {"hari": 1},
    "CL5% jual hari-2": {"hari": 2},
    "CL5% jual hari-5": {"hari": 5},
}


def ciri_saham(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = df["Open"], df["High"], df["Low"], df["Close"], df["Volume"].astype(float)
    ma = {n: c.rolling(n).mean() for n in (5, 10, 20, 50, 100)}
    v20 = v.rolling(20).mean().shift(1)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    hi20, lo20, hi60 = h.rolling(20).max(), l.rolling(20).min(), h.rolling(60).max()
    r1 = c.pct_change()
    tren = (c > ma[50]) & (ma[20] > ma[50]) & (ma[50] > ma[50].shift(10))
    distribusi = (((c < o) & (v >= 2.5 * v20)).rolling(5).max() > 0)
    j = tren & (c >= 0.97 * hi20) & (ma[20] > ma[20].shift(5) * 1.01) & (v / v20 >= 1.2) & (c > o) & ~distribusi
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26
    sd20 = c.rolling(20).std()
    f = pd.DataFrame({
        "r1": r1, "r3": c.pct_change(3), "r5": c.pct_change(5), "r10": c.pct_change(10),
        "r20": c.pct_change(20), "r60": c.pct_change(60),
        **{f"ma{n}": c / ma[n] - 1 for n in (5, 10, 20, 50, 100)},
        "kem20": ma[20] / ma[20].shift(5) - 1, "kem50": ma[50] / ma[50].shift(10) - 1,
        "rsi14": rsi(c, 14), "rsi2": rsi(c, 2), "atr": tr.rolling(14).mean() / c, "vol20": r1.rolling(20).std(),
        "rv1": v / v20, "rv5": v.rolling(5).mean() / v20, "nilai": np.log1p((c * v).rolling(20).mean()),
        "pos20": (c - lo20) / (hi20 - lo20).replace(0, np.nan), "jt20": c / hi20 - 1, "jt60": c / hi60 - 1,
        "jr20": c / lo20 - 1,
        "badan": (c - o) / o, "sumbu_atas": (h - np.maximum(o, c)) / c, "sumbu_bawah": (np.minimum(o, c) - l) / c,
        "pos_tutup": (c - l) / (h - l).replace(0, np.nan), "gap": o / c.shift() - 1,
        "naik5": (r1 > 0).rolling(5).sum(), "j": j.astype(float), "distribusi": distribusi.astype(float),
        "macd": macd / c, "macd_h": (macd - macd.ewm(span=9, adjust=False).mean()) / c,
        "bb_pos": (c - ma[20]) / (2 * sd20).replace(0, np.nan), "bb_lebar": 4 * sd20 / ma[20],
        "dekat_ara": (r1 > batas_ara(c.shift().fillna(c).to_numpy()) * 0.9).astype(float),
        "harga_log": np.log(c),
    }, index=df.index)
    # ciri akumulasi (pengganti data broker): aliran uang Chaikin, OBV, garis akumulasi/distribusi
    mfm = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    f["cmf20"] = (mfm * v).rolling(20).sum() / v.rolling(20).sum()
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    f["obv10"] = (obv - obv.shift(10)) / (v20 * 10)
    ad = (mfm.fillna(0) * v).cumsum()
    f["ad20"] = (ad - ad.shift(20)) / (v20 * 20)
    f["layak"] = ((c * v).rolling(20).mean() >= 1e9) & (c >= 50) & (v > 0)
    arr = [x.to_numpy() for x in (o, h, l, c)]
    atr_abs = tr.rolling(14).mean().to_numpy()
    for nama, kw in VARIASI_KELUAR.items():
        f["hasil" if not kw else "hk_" + nama] = hasil_transaksi(*arr, atr=atr_abs, **kw)
    f["tutup"] = c
    return f


def bangun_data(pakai_global: bool = True):
    t0 = time.time()
    kode = cfg.kode_semesta()
    data = jalankan.ambil_yahoo(kode)
    ihsg = data.pop("IHSG")
    print(f"Data: {len(data)} saham, IHSG {ihsg.index.min().date()} s.d. {ihsg.index.max().date()} "
          f"({time.time() - t0:.0f} dtk)")
    sektor = {}
    p = cfg.KELUAR / "fundamental.json"
    if p.exists():
        sektor = {f["kode"]: f.get("sektor") or "Lainnya" for f in json.loads(p.read_text())["saham"]}

    bagian = []
    for k, df in data.items():
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df = df[(df["Open"] > 0) & (df["Close"] > 0)]
        if len(df) < 150:
            continue
        f = ciri_saham(df)
        f["kode"] = k
        f["sektor"] = sektor.get(k, "Lainnya")
        bagian.append(f)
    d = pd.concat(bagian)
    d.index.name = "t"
    d = d.reset_index()

    # pasar (IHSG) dan keluasan pasar
    ic = ihsg["Close"]
    pasar = pd.DataFrame({
        "ihsg_r1": ic.pct_change(), "ihsg_r5": ic.pct_change(5), "ihsg_r20": ic.pct_change(20),
        "ihsg_ma20": ic / ic.rolling(20).mean() - 1, "ihsg_ma50": ic / ic.rolling(50).mean() - 1,
        "ihsg_rsi": rsi(ic, 14),
    })
    pasar.index = pd.to_datetime(pasar.index)
    d = d.merge(pasar, left_on="t", right_index=True, how="left")
    # global & makro (jurnal Binus): kurs, minyak, emas, batu bara, S&P 500 — nilai hari SEBELUMNYA
    try:
        if not pakai_global:
            raise RuntimeError("dilewati (tidak dipakai strategi harian)")
        import yfinance as yf
        gl = yf.download(["IDR=X", "BZ=F", "GC=F", "MTF=F", "^GSPC"], period="5y", interval="1d",
                         auto_adjust=True, progress=False)["Close"]
        gl.index = pd.to_datetime(gl.index).tz_localize(None)
        nama_gl = {"IDR=X": "usdidr", "BZ=F": "brent", "GC=F": "emas", "MTF=F": "batubara", "^GSPC": "sp500"}
        fg = pd.DataFrame(index=gl.index)
        for sim, nm in nama_gl.items():
            if sim in gl:
                x = gl[sim].ffill()
                fg[f"g_{nm}_r1"] = x.pct_change()
                fg[f"g_{nm}_r5"] = x.pct_change(5)
        fg = fg.shift(1)  # hanya informasi yang sudah ada sebelum hari t
        fg = fg.reindex(pd.date_range(fg.index.min(), fg.index.max())).ffill()
        d = d.merge(fg, left_on="t", right_index=True, how="left")
        print(f"Ciri global: {list(fg.columns)}")
    except Exception as e:  # noqa: BLE001
        print("  ! data global gagal:", e)
    g = d.groupby("t")
    d["luas_ma20"] = g["ma20"].transform(lambda x: (x > 0).mean())
    d["luas_r5"] = g["r5"].transform("median")
    # peringkat antarsaham per hari (0-1)
    for c in ("r5", "r20", "r60", "rv1", "rsi14", "jt20", "nilai", "vol20", "kem20"):
        d[f"pk_{c}"] = g[c].rank(pct=True)
    # sektor
    gs = d.groupby(["t", "sektor"])
    d["sek_r5"] = gs["r5"].transform("mean")
    d["sek_r20"] = gs["r20"].transform("mean")
    d["rel_sek20"] = d["r20"] - d["sek_r20"]
    d["hari"] = d["t"].dt.dayofweek
    d = d.replace([np.inf, -np.inf], np.nan)

    CIRI = [c for c in d.columns if c not in ("t", "kode", "sektor", "layak", "hasil", "tutup") and not c.startswith("hk_")]
    KELOMPOK = {
        "global": [c for c in CIRI if c.startswith("g_")],
        "akumulasi": ["cmf20", "obv10", "ad20"],
    }
    d = d.dropna(subset=["ma100", "r60", "rv1", "ihsg_ma50"])
    print(f"Baris: {len(d):,}, ciri: {len(CIRI)}, layak: {int(d['layak'].sum()):,} ({time.time() - t0:.0f} dtk)")

    return d, CIRI, KELOMPOK, t0


def main():
    d, CIRI, KELOMPOK, t0 = bangun_data()
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    MODEL = {
        "GB-klasifikasi": lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.04, max_depth=5,
                                                                 min_samples_leaf=300, l2_regularization=1.0,
                                                                 random_state=0),
        "GB-regresi": lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_depth=5,
                                                            min_samples_leaf=300, l2_regularization=1.0,
                                                            loss="absolute_error", random_state=0),
        "Logistik": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                          LogisticRegression(C=0.05, max_iter=500)),
    }
    lat = d[d["layak"] & d["hasil"].notna()].copy()
    lat["menang"] = (lat["hasil"] > 0).astype(int)
    lat["hasil_c"] = lat["hasil"].clip(-0.15, 0.15)
    uji_semua = d[d["layak"] & d["hasil"].notna() & (d["t"] >= MULAI_UJI)].copy()
    kuartal = pd.period_range(uji_semua["t"].min(), uji_semua["t"].max(), freq="Q")
    tgl = np.array(sorted(d["t"].unique()))
    skor = {m: pd.Series(np.nan, index=uji_semua.index) for m in MODEL}
    for q in kuartal:
        awal, akhir = q.start_time, q.end_time
        idx_awal = np.searchsorted(tgl, np.datetime64(awal))
        batas = tgl[max(0, idx_awal - 5)]
        tr = lat[lat["t"] < batas]
        te = uji_semua[(uji_semua["t"] >= awal) & (uji_semua["t"] <= akhir)]
        if te.empty or len(tr) < 20000:
            continue
        for m, buat in MODEL.items():
            mdl = buat()
            if m == "GB-regresi":
                mdl.fit(tr[CIRI], tr["hasil_c"])
                skor[m].loc[te.index] = mdl.predict(te[CIRI])
            else:
                mdl.fit(tr[CIRI], tr["menang"])
                skor[m].loc[te.index] = mdl.predict_proba(te[CIRI])[:, 1]
        print(f"  kuartal {q}: latih {len(tr):,} baris, uji {len(te):,} ({time.time() - t0:.0f} dtk)", flush=True)
    for m in MODEL:
        uji_semua[f"s_{m}"] = skor[m]
    uji_semua["s_Gabungan"] = sum(uji_semua.groupby("t")[f"s_{m}"].rank(pct=True) for m in MODEL) / len(MODEL)
    uji_semua["s_Momentum20"] = uji_semua["r20"]
    uji_semua = uji_semua.dropna(subset=[f"s_{m}" for m in MODEL])
    uji_semua["naik_ihsg"] = uji_semua["ihsg_ma20"] > 0

    def ringkas(r, nama):
        r = np.asarray(r) * 100
        if len(r) == 0:
            return {"strategi": nama, "n": 0}
        m, k = r[r > 0], r[r <= 0]
        return {"strategi": nama, "n": len(r), "rata%": round(r.mean(), 3), "median%": round(float(np.median(r)), 2),
                "menang%": round(len(m) / len(r) * 100, 1), "PF": round(m.sum() / -k.sum(), 2) if k.sum() else None,
                "t": round(r.mean() / (r.std() / np.sqrt(len(r))), 2) if len(r) > 2 else None}

    def pilih(df, kol, K, saring=None):
        x = df if saring is None else df[saring(df)]
        return x.sort_values(kol, ascending=False).groupby("t").head(K)

    baris, per_tahun = [], []
    strategi = {}
    for nama in list(MODEL) + ["Gabungan", "Momentum20"]:
        for K in (3, 5, 10):
            strategi[f"{nama} top{K}"] = pilih(uji_semua, f"s_{nama}", K)
            strategi[f"{nama} top{K} +IHSG>MA20"] = pilih(uji_semua, f"s_{nama}", K, lambda x: x["naik_ihsg"])
    strategi["Aturan J (semua sinyal)"] = uji_semua[uji_semua["j"] == 1]
    strategi["Aturan J +IHSG>MA20"] = uji_semua[(uji_semua["j"] == 1) & uji_semua["naik_ihsg"]]
    strategi["Aturan J diurut Gabungan top3"] = pilih(uji_semua[uji_semua["j"] == 1], "s_Gabungan", 3)
    strategi["Acak (semua saham layak)"] = uji_semua
    for nama, x in strategi.items():
        baris.append(ringkas(x["hasil"], nama))
        for th, y in x.groupby(x["t"].dt.year):
            per_tahun.append({"strategi": nama, "tahun": th, **{k: v for k, v in ringkas(y["hasil"], nama).items() if k != "strategi"}})
    hasil = pd.DataFrame(baris).sort_values("rata%", ascending=False)
    print("\nHASIL_RISET_MULAI (periode uji", uji_semua["t"].min().date(), "s.d.", uji_semua["t"].max().date(), ")")
    print(hasil.to_string(index=False))
    pt = pd.DataFrame(per_tahun)
    unggul = hasil.head(8)["strategi"].tolist() + ["Aturan J +IHSG>MA20", "Acak (semua saham layak)"]
    print("\nPER TAHUN (8 teratas + pembanding):")
    print(pt[pt["strategi"].isin(unggul)].pivot_table(index="strategi", columns="tahun", values="rata%").round(3).to_string())

    # sumbangan kelompok ciri: latih ulang GB-klasifikasi tanpa kelompok itu (walk-forward sama)
    def wf_tanpa(buang):
        kol = [c for c in CIRI if c not in buang]
        sk = pd.Series(np.nan, index=uji_semua.index)
        for q in kuartal:
            idx_awal = np.searchsorted(tgl, np.datetime64(q.start_time))
            tr = lat[lat["t"] < tgl[max(0, idx_awal - 5)]]
            te = uji_semua[(uji_semua["t"] >= q.start_time) & (uji_semua["t"] <= q.end_time)]
            if te.empty or len(tr) < 20000:
                continue
            m = MODEL["GB-klasifikasi"]().fit(tr[kol], tr["menang"])
            sk.loc[te.index] = m.predict_proba(te[kol])[:, 1]
        return sk
    print("\nSUMBANGAN KELOMPOK CIRI (GB-klasifikasi top5 +IHSG>MA20, rata% per transaksi):")
    base = ringkas(pilih(uji_semua, "s_GB-klasifikasi", 5, lambda x: x["naik_ihsg"])["hasil"], "semua ciri")
    print(f"  semua ciri          : {base.get('rata%')} (n={base.get('n')}, menang {base.get('menang%')}%)")
    for nk, kol in KELOMPOK.items():
        if not kol:
            continue
        uji_semua[f"s_tanpa_{nk}"] = wf_tanpa(kol)
        r = ringkas(pilih(uji_semua.dropna(subset=[f"s_tanpa_{nk}"]), f"s_tanpa_{nk}", 5, lambda x: x["naik_ihsg"])["hasil"], nk)
        print(f"  tanpa ciri {nk:9s}: {r.get('rata%')} (n={r.get('n')}, menang {r.get('menang%')}%)")

    # variasi manajemen risiko pada pilihan yang sama (jurnal KES: batas rugi & ambil untung)
    print("\nVARIASI KELUAR (rata% per transaksi, menang%):")
    for nama_s in [hasil.iloc[0]["strategi"], "Aturan J +IHSG>MA20"]:
        x = strategi[nama_s]
        print(f"  pilihan: {nama_s}")
        for nk in VARIASI_KELUAR:
            kol = "hasil" if not VARIASI_KELUAR[nk] else "hk_" + nk
            r = ringkas(x[kol].dropna(), nk)
            print(f"    {nk:30s} rata {r.get('rata%')}%  menang {r.get('menang%')}%  PF {r.get('PF')}  n={r.get('n')}")

    # pentingnya ciri model GB-klasifikasi terakhir (pada kuartal uji terakhir)
    from sklearn.inspection import permutation_importance
    q = kuartal[-1]
    tr = lat[lat["t"] < q.start_time]
    te = uji_semua[uji_semua["t"] >= q.start_time]
    if len(te) > 2000:
        mdl = MODEL["GB-klasifikasi"]().fit(tr[CIRI], tr["menang"])
        contoh = te.sample(min(len(te), 20000), random_state=0)
        pi = permutation_importance(mdl, contoh[CIRI], contoh["hasil"] > 0, scoring="roc_auc", n_repeats=3, random_state=0)
        imp = pd.Series(pi.importances_mean, index=CIRI).sort_values(ascending=False)
        print("\nCIRI TERPENTING (penurunan AUC bila diacak):")
        print(imp.head(15).round(4).to_string())
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    main()
