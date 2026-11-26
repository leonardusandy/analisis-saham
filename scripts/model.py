"""Model peluang naik/turun 3 hari bursa ke depan untuk semua saham.

Cara kerja:
  - Ciri (fitur) dihitung dari riwayat harga harian tiap saham (tren, momentum, volume, posisi
    harga, RSI, ATR, sinyal aturan J, jejak distribusi) dan kondisi pasar (indeks rata-rata semua
    saham: naik/turun 5 hari, di atas/bawah MA20).
  - Sasaran: harga penutupan 3 hari bursa kemudian lebih tinggi dari penutupan hari ini.
  - Model: HistGradientBoostingClassifier (scikit-learn).
  - Uji jujur (walk-forward): model dilatih hanya dengan data sebelum 60 hari bursa terakhir,
    lalu diuji pada 60 hari terakhir yang tidak pernah dilihatnya. Angka akurasi di web berasal
    dari uji ini, bukan dari data latih.
  - Setelah diuji, model dilatih ulang dengan semua data berlabel, lalu memperkirakan peluang
    naik untuk setiap saham pada tanggal data terakhir.
Hasil: <DATA_KELUAR>/model.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

WIB = timezone(timedelta(hours=7))
H = 3            # horizon hari bursa
HARI_UJI = 60    # panjang periode uji walk-forward

NAMA_FITUR = {
    "r1": "Perubahan 1 hari", "r5": "Perubahan 5 hari", "r20": "Perubahan 20 hari",
    "ma20": "Jarak ke MA20", "ma50": "Jarak ke MA50", "kemiringan20": "Kemiringan MA20 (5 hari)",
    "rsi": "RSI 14", "rv": "Volume × rata-rata", "atr": "ATR % harga", "posisi20": "Posisi dalam rentang 20 hari",
    "jarak_tinggi20": "Jarak ke tertinggi 20 hari", "badan": "Badan candle", "posisi_tutup": "Posisi penutupan hari ini",
    "j": "Sinyal aturan J", "distribusi": "Jejak distribusi 5 hari", "nilai": "Nilai transaksi (log)",
    "pasar5": "Pasar 5 hari", "pasar_ma20": "Pasar di atas MA20", "relatif20": "Kekuatan relatif 20 hari",
}


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def fitur_saham(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = df["o"], df["h"], df["l"], df["c"], df["v"].astype(float)
    ma20, ma50 = c.rolling(20).mean(), c.rolling(50).mean()
    v20 = v.rolling(20).mean().shift(1)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
    rentang = (h - l).replace(0, np.nan)
    tren_naik = (c > ma50) & (ma20 > ma50) & (ma50 > ma50.shift(10))
    distribusi = (((c < o) & (v >= 2.5 * v20)).rolling(5).max() > 0)
    j = tren_naik & (c >= 0.97 * hi20) & (ma20 > ma20.shift(5) * 1.01) & (v / v20 >= 1.2) & (c > o) & ~distribusi
    f = pd.DataFrame({
        "r1": c.pct_change(), "r5": c.pct_change(5), "r20": c.pct_change(20),
        "ma20": c / ma20 - 1, "ma50": c / ma50 - 1, "kemiringan20": ma20 / ma20.shift(5) - 1,
        "rsi": rsi(c), "rv": v / v20, "atr": tr.rolling(14).mean() / c,
        "posisi20": (c - lo20) / (hi20 - lo20).replace(0, np.nan), "jarak_tinggi20": c / hi20 - 1,
        "badan": (c - o) / o, "posisi_tutup": (c - l) / rentang,
        "j": j.astype(float), "distribusi": distribusi.astype(float),
        "nilai": np.log1p((c * v).rolling(20).mean()),
    }, index=df.index)
    f["target"] = (c.shift(-H) > c).astype(float).where(c.shift(-H).notna())
    f["hasil"] = c.shift(-H) / c - 1
    return f


def main():
    k = cfg.KELUAR
    rk = json.loads((k / "ringkasan.json").read_text())
    info = {s["kode"]: s for s in rk["saham"]}
    bagian, harga = [], {}
    for p in sorted((k / "saham").glob("*.json")):
        d = json.loads(p.read_text())
        df = pd.DataFrame(d["lilin"]).set_index("t")
        if len(df) < 80:
            continue
        f = fitur_saham(df)
        f["kode"] = d["kode"]
        bagian.append(f)
        harga[d["kode"]] = df["c"]
    data = pd.concat(bagian)
    data.index.name = "t"
    data = data.reset_index()

    # kondisi pasar: indeks rata-rata (bobot sama) dari perubahan harian semua saham
    ret = pd.DataFrame(harga).sort_index().pct_change().clip(-0.35, 0.35)
    pasar = (1 + ret.mean(axis=1).fillna(0)).cumprod()
    pasar_df = pd.DataFrame({"pasar5": pasar.pct_change(5), "pasar_ma20": (pasar > pasar.rolling(20).mean()).astype(float),
                             "pasar20": pasar.pct_change(20)})
    data = data.merge(pasar_df, left_on="t", right_index=True, how="left")
    data["relatif20"] = data["r20"] - data["pasar20"]
    kolom = list(NAMA_FITUR)
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=["ma50", "r20", "rv", "pasar5"])

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    def model_baru():
        return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=4, min_samples_leaf=200,
                                              l2_regularization=1.0, random_state=0)

    tanggal = sorted(data["t"].unique())
    berlabel = data[data["target"].notna()]
    tgl_label = sorted(berlabel["t"].unique())
    batas_uji = tgl_label[-HARI_UJI]
    # jeda H hari agar label data latih tidak menyentuh periode uji
    tgl_latih_akhir = tgl_label[max(0, tgl_label.index(batas_uji) - H)]
    latih = berlabel[berlabel["t"] < tgl_latih_akhir]
    uji = berlabel[berlabel["t"] >= batas_uji]

    m = model_baru().fit(latih[kolom], latih["target"])
    p_uji = m.predict_proba(uji[kolom])[:, 1]
    y = uji["target"].to_numpy()
    akurasi = float(((p_uji >= 0.5) == (y == 1)).mean())
    dasar = float(max(y.mean(), 1 - y.mean()))
    keranjang = []
    for a, b in [(0, .4), (.4, .45), (.45, .5), (.5, .55), (.55, .6), (.6, 1.01)]:
        sel = (p_uji >= a) & (p_uji < b)
        if sel.sum():
            keranjang.append({"rentang": f"{int(a * 100)}–{min(100, int(b * 100))}%", "n": int(sel.sum()),
                              "perkiraan": round(float(p_uji[sel].mean()) * 100, 1),
                              "kenyataan": round(float(y[sel].mean()) * 100, 1),
                              "rata_hasil": round(float(uji["hasil"].to_numpy()[sel].mean()) * 100, 2)})
    yakin = (p_uji >= 0.6) | (p_uji <= 0.4)
    validasi = {
        "periode": f"{batas_uji} s.d. {tgl_label[-1]}", "n": int(len(uji)), "akurasi": round(akurasi * 100, 1),
        "dasar": round(dasar * 100, 1), "persen_naik_nyata": round(float(y.mean()) * 100, 1),
        "auc": round(float(roc_auc_score(y, p_uji)), 3),
        "akurasi_yakin": round(float(((p_uji[yakin] >= 0.5) == (y[yakin] == 1)).mean()) * 100, 1) if yakin.sum() else None,
        "n_yakin": int(yakin.sum()), "keranjang": keranjang, "n_latih": int(len(latih)),
    }

    # pentingnya ciri: penurunan AUC bila satu ciri diacak (pada sampel uji)
    rng = np.random.default_rng(0)
    contoh = uji.sample(min(len(uji), 15000), random_state=0)
    auc0 = roc_auc_score(contoh["target"], m.predict_proba(contoh[kolom])[:, 1])
    penting = []
    for c in kolom:
        x = contoh[kolom].copy()
        x[c] = rng.permutation(x[c].to_numpy())
        penting.append({"fitur": NAMA_FITUR[c], "turun_auc": round(float(auc0 - roc_auc_score(contoh["target"], m.predict_proba(x)[:, 1])), 4)})
    penting.sort(key=lambda x: -x["turun_auc"])

    # latih ulang dengan semua data berlabel, perkirakan tanggal terakhir
    m = model_baru().fit(berlabel[kolom], berlabel["target"])
    akhir = data[data["t"] == tanggal[-1]].copy()
    akhir["p"] = m.predict_proba(akhir[kolom])[:, 1]
    # perkiraan perubahan: rata-rata hasil nyata di uji untuk peluang yang mirip
    pk = pd.Series(p_uji)
    hasil_uji = uji["hasil"].reset_index(drop=True)
    tepi = np.quantile(p_uji, np.linspace(0, 1, 11))
    rata_desil = [float(hasil_uji[(pk >= tepi[i]) & (pk <= tepi[i + 1])].mean()) for i in range(10)]

    def perkiraan(p):
        i = int(np.clip(np.searchsorted(tepi, p, side="right") - 1, 0, 9))
        return round(rata_desil[i] * 100, 2)

    prediksi = []
    for _, r in akhir.iterrows():
        s = info.get(r["kode"], {})
        p = float(r["p"])
        prediksi.append({
            "kode": r["kode"], "p": round(p * 100, 1), "arah": "naik" if p >= 0.5 else "turun",
            "keyakinan": "tinggi" if p >= 0.6 or p <= 0.4 else "sedang" if p >= 0.55 or p <= 0.45 else "rendah",
            "perkiraan_pct": perkiraan(p), "j": bool(r["j"]), "likuid": bool(s.get("likuid")),
            "rsi": round(float(r["rsi"]), 1) if pd.notna(r["rsi"]) else None,
        })
    prediksi.sort(key=lambda x: -x["p"])
    out = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "tanggal": tanggal[-1], "horizon": H,
        "validasi": validasi, "penting": penting, "prediksi": prediksi,
    }
    (k / "model.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"Model: uji {validasi['periode']}: akurasi {validasi['akurasi']}% (dasar {validasi['dasar']}%), "
          f"AUC {validasi['auc']}, {len(prediksi)} saham diperkirakan.")


if __name__ == "__main__":
    main()
