"""Uji beberapa aturan penyaringan untuk gaya pegang 1-3 hari dengan batas rugi maksimal -5%.

Sinyal dihitung saat penutupan hari t, beli di harga pembukaan t+1 (tidak mengintip masa depan).
Saham harus ramai saat sinyal (rata-rata nilai transaksi 20 hari >= Rp1 M) dan harga >= 50.
Biaya beli 0,15% dan jual 0,25% sudah dihitung. Satu posisi per saham pada satu waktu.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
import jalankan  # noqa: E402

cfg.PERIODE = "3y"
B, J = cfg.BIAYA_BELI, cfg.BIAYA_JUAL


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def sinyal(df, ihsg_naik):
    o, h, l, c, v = df["Open"], df["High"], df["Low"], df["Close"], df["Volume"]
    ma5, ma20, ma50, ma200 = (c.rolling(n).mean() for n in (5, 20, 50, 200))
    atr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1).rolling(14).mean()
    rv = v / v.rolling(20).mean().shift(1)
    posisi = (c - l) / (h - l).replace(0, np.nan)
    ramai = ((c * v).rolling(20).mean() >= 1e9) & (c >= 50)
    tren_naik = (c > ma50) & (ma20 > ma50) & (ma50 > ma50.shift(10))
    hi20 = h.shift(1).rolling(20).max()
    sup = pd.concat([l.rolling(10).min(), ma20, ma50], axis=1)
    sup = sup.where(sup.lt(c, axis=0)).max(axis=1)
    rentang = (h.rolling(20).max() - l.rolling(20).min()) / c
    datar = ~tren_naik & (rentang < 0.12) & (c > ma50)
    r2 = rsi(c, 2)
    s = {
        "A. Tembus resistance 20 hari + volume": (c > hi20) & (rv >= 1.5) & (posisi >= 0.7) & (c > ma50),
        "B. Pantul MA20 di tren naik": tren_naik & (l <= ma20 * 1.01) & (c > ma20) & (c > o),
        "C. Jenuh jual RSI2<10 di atas MA200": (c > ma200) & (r2 < 10),
        "D. Pantul support (aturan Pilihan Harian)": (tren_naik | datar) & (l <= sup * 1.02) & (c > o),
        "E. Tren naik kuat ^^^ + volume": tren_naik & (c >= 0.97 * h.rolling(20).max()) & (ma20 > ma20.shift(5) * 1.01) & (rv >= 1.2) & (c > o),
    }
    # --- aturan dari materi Stock School & Hengky Adinata ---
    v20 = v.rolling(20).mean().shift(1)
    lonjak = (v >= 3 * v20) & (c > c.shift(1))
    s["F. HA: lonjakan volume lalu volume mengering saat koreksi"] = (
        (lonjak.shift(1).rolling(10).max() > 0) & (v < 0.6 * v20) & (c <= c.shift(1)) & (c > ma20))
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26; sig = macd.ewm(span=9, adjust=False).mean()
    s["G. SS: MACD potong ke atas, di atas 0, harga > MA20"] = (macd > sig) & (macd.shift(1) <= sig.shift(1)) & (macd > 0) & (c > ma20)
    tk = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kj = (h.rolling(26).max() + l.rolling(26).min()) / 2
    awan = pd.concat([((tk + kj) / 2).shift(26), ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)], axis=1).max(axis=1)
    s["H. SS: Ichimoku di atas awan + tenkan potong kijun"] = (c > awan) & (tk > kj) & (tk.shift(1) <= kj.shift(1))
    bawah20, atas20 = l.rolling(20).min(), h.rolling(20).max()
    s["I. SS: sideways, beli di dasar rentang"] = (rentang < 0.12) & (c <= bawah20 + 0.25 * (atas20 - bawah20)) & (c > o)
    s["J. E + HA: tren kuat ^^^ tanpa candle merah bervolume besar 5 hari"] = s["E. Tren naik kuat ^^^ + volume"] & ~(
        ((c < o) & (v >= 2.5 * v20)).rolling(5).max() > 0)
    s = {k: (x & ramai).fillna(False) for k, x in s.items()}
    return s, atr, ma5


def simulasi(df, msk, atr, ma5, cara):
    o, h, l, c = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close"))
    idx, a, m5 = np.where(msk.to_numpy())[0], atr.to_numpy(), ma5.to_numpy()
    hasil, bebas = [], -1
    for i in idx:
        if i <= bebas or i + 1 >= len(c) or not o[i + 1] > 0:
            continue
        e = o[i + 1]
        if cara == "pegang3":
            stop, target, hari = e * 0.95, None, 3
        elif cara == "atr":
            stop, target, hari = max(e * 0.95, e - 1.0 * a[i]), e + 1.5 * a[i], 3
        else:  # "pegang1": jual di penutupan hari pertama
            stop, target, hari = e * 0.95, None, 1
        keluar, j = None, i + 1
        for j in range(i + 1, min(i + 1 + hari, len(c))):
            if j > i + 1 and o[j] <= stop:
                keluar = o[j]; break  # buka di bawah batas rugi
            if l[j] <= stop:
                keluar = stop; break  # anggap batas rugi kena lebih dulu
            if target and j > i + 1 and o[j] >= target:
                keluar = o[j]; break
            if target and h[j] >= target:
                keluar = target; break
        if keluar is None:
            keluar = c[j]
        bebas = j
        hasil.append((df.index[i], keluar * (1 - J) / (e * (1 + B)) - 1))
    return hasil


def ringkas(tr):
    if not tr:
        return None
    r = np.array([x[1] for x in tr]) * 100
    t = pd.to_datetime([x[0] for x in tr])
    menang, kalah = r[r > 0], r[r <= 0]
    tengah = t.min() + (t.max() - t.min()) / 2
    return {
        "n": len(r), "menang%": round(len(menang) / len(r) * 100, 1), "rata%": round(r.mean(), 2),
        "median%": round(float(np.median(r)), 2), "PF": round(menang.sum() / -kalah.sum(), 2) if len(kalah) and kalah.sum() else None,
        "rata_menang%": round(menang.mean(), 2) if len(menang) else 0, "rata_kalah%": round(kalah.mean(), 2) if len(kalah) else 0,
        "paruh1%": round(r[t < tengah].mean(), 2), "paruh2%": round(r[t >= tengah].mean(), 2),
        "per_bulan": round(len(r) / max(1, (t.max() - t.min()).days / 30.4), 1),
    }


def main():
    kode = cfg.kode_semesta()
    data = jalankan.ambil_yahoo(kode)
    ihsg = data.pop("IHSG")["Close"]
    ihsg_naik = ihsg > ihsg.rolling(20).mean()
    print(f"Data: {len(data)} saham, {ihsg.index.min().date()} s.d. {ihsg.index.max().date()}")
    kumpul = {}
    for k, df in data.items():
        df = df.dropna(subset=["Open", "Close"])
        df = df[df["Volume"] > 0]
        if len(df) < 250:
            continue
        sig, atr, ma5 = sinyal(df, ihsg_naik)
        naik = ihsg_naik.reindex(df.index).fillna(False)
        for nama, m in sig.items():
            for cara in ("pegang1", "pegang3", "atr"):
                for rezim, mm in (("semua", m), ("IHSG>MA20", m & naik)):
                    kumpul.setdefault((nama, cara, rezim), []).extend(simulasi(df, mm, atr, ma5, cara))
    baris = []
    for (nama, cara, rezim), tr in sorted(kumpul.items()):
        rk = ringkas(tr)
        if rk:
            baris.append({"aturan": nama, "keluar": cara, "pasar": rezim, **rk})
    t = pd.DataFrame(baris)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 200)
    print("HASIL_UJI_MULAI")
    print(t.to_string(index=False))
    print("HASIL_JSON " + json.dumps(baris))


if __name__ == "__main__":
    main()
