"""Pilihan saham harian: tabel uptrend & sideways, tanda, sektor, dan analisa entry/R1/R2/CL.

Semua aturan dihitung dari riwayat harga harian (tanpa data broker), sehingga bisa diulang
dan diuji. Hasil: <DATA_KELUAR>/stockpick.json

ATURAN (juga ditampilkan di web):
  Uptrend   : harga > MA20 > MA50 dan MA50 naik dibanding 10 hari lalu.
  Downtrend : harga < MA20 < MA50 dan MA50 turun dibanding 10 hari lalu.
  Sideways  : bukan uptrend/downtrend, dan rentang harga 20 hari < 12% dari harga.
  Tingkat ^ : 1 + jumlah syarat terpenuhi (maks 3):
                (a) harga >= 97% harga tertinggi 20 hari, (b) MA20 naik >= 1% dalam 5 hari,
                (c) rata-rata volume 5 hari > 1,1x rata-rata 20 hari.
  Sejak     : hari pertama status saat ini berlangsung tanpa putus.
  S/R       : support = level tertinggi di bawah harga dari {terendah 10 hari, MA20, MA50};
              resistance = tertinggi 20 hari (atau 60 hari) di atas harga, atau harga + 2 ATR.
  * kuat    : harga terendah menyentuh area support (±1%) minimal 3 kali terpisah (berjarak
              >= 3 hari) pada 60 sampai 5 hari terakhir.
  Murah     : PER positif < 80% median PER sektornya, atau PBV < 1 dengan ROE > 8%.
  Warna     : Baru masuk (status berlangsung <= 2 hari), Sinyal beli (memantul di support
              atau menembus resistance dengan volume >= 1,5x), Naik/turun pangkat (tingkat
              berubah dari kemarin).
  Analisa   : saham uptrend/sideways bersinyal beli & ramai. Entry = support s.d. harga
              penutupan; R1 = resistance terdekat; R2 = resistance berikutnya;
              CL (batas rugi) = support - 0,3 ATR, minimal 1 ATR di bawah harga. Hanya ditampilkan bila jarak R1 minimal
              1,2x jarak CL dan CL tidak lebih dari 7% di bawah harga.
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
from analisis import bulatkan  # noqa: E402

WIB = timezone(timedelta(hours=7))
KODE_SEKTOR = {
    "Barang Konsumen Primer": "C", "Keuangan": "F", "Energi": "E", "Perindustrian": "IN",
    "Barang Konsumen Nonprimer": "CC", "Transportasi": "TL", "Kesehatan": "H",
    "Telekomunikasi & Media": "I", "Utilitas": "I", "Infrastruktur": "I", "Bahan Baku": "B",
    "Teknologi": "T", "Properti": "P",
}


def status_harian(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]
    m20, m50 = c.rolling(20).mean(), c.rolling(50).mean()
    naik50, turun50 = m50 > m50.shift(10), m50 < m50.shift(10)
    up = (c > m20) & (m20 > m50) & naik50
    down = (c < m20) & (m20 < m50) & turun50
    rentang = (h.rolling(20).max() - l.rolling(20).min()) / c
    side = ~up & ~down & (rentang < 0.12)
    st = pd.Series(np.select([up, down, side], ["up", "down", "side"], "lain"), index=df.index)
    st[m50.isna()] = "lain"
    k1 = c >= 0.97 * h.rolling(20).max()
    k2 = m20 > m20.shift(5) * 1.01
    k3 = v.rolling(5).mean() > 1.1 * v.rolling(20).mean()
    tingkat = (1 + (k1.astype(int) + k2.astype(int) + k3.astype(int)).clip(upper=2)).where(up | side, 0)
    return pd.DataFrame({"st": st, "tingkat": tingkat, "m20": m20, "m50": m50})


def tanggal_mulai(st: pd.Series) -> int:
    """Jumlah hari status terakhir berlangsung."""
    akhir, n = st.iloc[-1], 0
    for s in reversed(st.tolist()):
        if s != akhir:
            break
        n += 1
    return n


def main():
    k = cfg.KELUAR
    rk = json.loads((k / "ringkasan.json").read_text())
    saham = {s["kode"]: s for s in rk["saham"]}
    fund = {}
    if (k / "fundamental.json").exists():
        fund = {s["kode"]: s for s in json.loads((k / "fundamental.json").read_text())["saham"]}

    # median PER per sektor (untuk tanda murah)
    per_sektor = {}
    for f in fund.values():
        if f.get("per") and 0 < f["per"] < 200:
            per_sektor.setdefault(f.get("sektor"), []).append(f["per"])
    median_per = {s: statistics.median(v) for s, v in per_sektor.items() if len(v) >= 3}

    baris, keluar, harga_sektor = [], [], {}
    for kode, s in saham.items():
        p = k / "saham" / f"{kode}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        df = pd.DataFrame(d["lilin"]).set_index("t")
        if len(df) < 80:
            continue
        f = fund.get(kode, {})
        sektor = f.get("sektor") or "Lainnya"
        if s.get("kap"):
            harga_sektor.setdefault(sektor, []).append((df["c"], s["kap"]))
        hs = status_harian(df)
        st, tk = hs["st"].iloc[-1], int(hs["tingkat"].iloc[-1])
        st_k, tk_k = hs["st"].iloc[-2], int(hs["tingkat"].iloc[-2])
        if st_k in ("up", "side") and st not in ("up", "side") and s.get("likuid"):
            keluar.append({"kode": kode, "dari": st_k, "ke": st, "sektor": KODE_SEKTOR.get(sektor, "")})
        if st not in ("up", "side") or not s.get("likuid"):
            continue

        c = float(df["c"].iloc[-1])
        atr = s.get("atr") or (df["h"] - df["l"]).tail(14).mean()
        kandidat_s = [x for x in [df["l"].tail(10).min(), hs["m20"].iloc[-1], hs["m50"].iloc[-1]] if x and x < c]
        support = max(kandidat_s) if kandidat_s else c - 2 * atr
        r20, r60, r120 = df["h"].tail(20).max(), df["h"].tail(60).max(), df["h"].tail(120).max()
        r1 = next((x for x in [r20, r60, r120] if x > c * 1.005), c + 2 * atr)
        r2 = next((x for x in [r60, r120] if x > r1 * 1.01), r1 + 1.5 * atr)
        # sentuhan terpisah: hari ketika harga terendah berada ±1% dari support, berjarak >= 3 hari
        lama_l = df["l"].iloc[-60:-5]  # abaikan 5 hari terakhir (support biasanya dibentuk dari sana)
        dekat = np.where(((lama_l - support).abs() / support <= 0.01).to_numpy())[0]
        sentuh, terakhir = 0, -10
        for i in dekat:
            if i - terakhir >= 3:
                sentuh += 1
            terakhir = i
        murah = bool(
            (f.get("per") and f["per"] > 0 and sektor in median_per and f["per"] < 0.8 * median_per[sektor])
            or (f.get("pbv") and f["pbv"] < 1 and (f.get("roe") or 0) > 8))
        rv = s.get("rasio_vol") or 0
        o = float(df["o"].iloc[-1])
        tinggi20_lalu = df["h"].iloc[-21:-1].max()
        sinyal = bool((df["l"].iloc[-1] <= support * 1.02 and c > o) or (c > tinggi20_lalu and rv >= 1.5))
        lama = tanggal_mulai(hs["st"])
        warna = ("baru" if lama <= 2 else "beli" if sinyal else "naik" if tk > tk_k and st == st_k
                 else "turun" if tk < tk_k and st == st_k else None)
        baris.append({
            "kode": kode, "nama": f.get("nama"), "sektor": sektor, "sk": KODE_SEKTOR.get(sektor, ""),
            "lapis": s.get("lapis"), "grup": s.get("grup"), "status": st, "tingkat": tk,
            "support": bulatkan(support, "bawah"), "resistance": bulatkan(r1, "atas"), "r2": bulatkan(r2, "atas"),
            "kuat": sentuh >= 3, "murah": murah, "sejak": df.index[-lama], "hari": lama,
            "warna": warna, "sinyal": sinyal, "tutup": c, "ubah": s.get("perubahan_pct"), "atr": round(float(atr), 1),
            "skor": s.get("skor"), "rasio_vol": rv,
        })

    # ----- tren sektor: indeks berbobot kapitalisasi dari harga anggota -----
    sektor_hasil = []
    for nama, anggota in harga_sektor.items():
        if len(anggota) < 2 or nama == "Lainnya":
            continue
        idx = None
        total = sum(w for _, w in anggota)
        for ser, w in anggota:
            ser = ser.tail(80)
            norm = ser / ser.iloc[0] * w / total
            idx = norm if idx is None else idx.add(norm, fill_value=np.nan)
        idx = idx.dropna()
        if len(idx) < 30:
            continue
        m20 = idx.rolling(20).mean().iloc[-1]
        ubah20 = (idx.iloc[-1] / idx.iloc[-21] - 1) * 100
        arah = "better" if idx.iloc[-1] > m20 and ubah20 > 0 else "worst" if idx.iloc[-1] < m20 and ubah20 < 0 else "netral"
        sektor_hasil.append({"nama": nama, "kode": KODE_SEKTOR.get(nama, ""), "arah": arah,
                             "ubah20": round(float(ubah20), 2), "jumlah": len(anggota)})
    sektor_hasil.sort(key=lambda x: -x["ubah20"])
    lebih_baik = {x["nama"] for x in sektor_hasil if x["arah"] == "better"}

    # ----- analisa harian -----
    kand = [b for b in baris if b["sinyal"]]
    kand.sort(key=lambda b: (-b["tingkat"], b["sektor"] not in lebih_baik, b["lapis"] or 9, -(b["skor"] or 0), -(b["rasio_vol"] or 0)))
    analisa = []
    for b in kand:
        if len(analisa) >= 6:
            break
        lo = bulatkan(max(b["support"], b["tutup"] - 0.5 * b["atr"]), "bawah")
        hi = bulatkan(b["tutup"], "bawah")
        r1 = b["resistance"] if b["resistance"] > hi * 1.01 else bulatkan(hi + b["atr"], "atas")
        r2 = b["r2"] if b["r2"] > r1 * 1.01 else bulatkan(r1 + b["atr"], "atas")
        cl = bulatkan(b["support"] - 0.3 * b["atr"], "bawah")
        if cl >= lo:
            cl = bulatkan(lo - 0.5 * b["atr"], "bawah")
        cl = min(cl, bulatkan(hi - b["atr"], "bawah"))  # minimal 1 ATR di bawah harga agar tidak kena gerak harian biasa
        untung, rugi = r1 / hi - 1, 1 - cl / hi
        if rugi <= 0 or rugi > 0.07 or untung / rugi < 1.2:
            continue  # rasio untung:rugi kurang menarik atau batas rugi terlalu jauh
        analisa.append({
            "kode": b["kode"], "sk": b["sk"], "status": b["status"], "tingkat": b["tingkat"],
            "entry": [lo, hi], "r1": r1, "r2": r2, "cl": cl,
            "untung_r1_pct": round(untung * 100, 1), "rugi_cl_pct": round(-rugi * 100, 1), "rasio": round(untung / rugi, 2),
            "alasan": ("memantul di support" if b["tutup"] <= b["support"] * 1.05 else "menembus resistance dengan volume besar")
                      + (", sektor sedang menguat" if b["sektor"] in lebih_baik else ""),
        })

    urut = lambda b: (-b["tingkat"], b["sejak"])  # noqa: E731
    data = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "tanggal": rk["tanggal_data"],
        "uptrend": sorted([b for b in baris if b["status"] == "up"], key=urut),
        "sideways": sorted([b for b in baris if b["status"] == "side"], key=urut),
        "keluar": keluar,
        "sektor": sektor_hasil,
        "analisa": analisa,
        "aturan": __doc__.split("ATURAN (juga ditampilkan di web):")[1].strip(),
    }
    (k / "stockpick.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str))
    print(f"Stockpick: uptrend {len(data['uptrend'])}, sideways {len(data['sideways'])}, keluar {len(keluar)}, "
          f"analisa {len(analisa)}, sektor better {len(lebih_baik)}, support kuat {sum(b['kuat'] for b in baris)}, "
          f"murah {sum(b['murah'] for b in baris)}, ^^^ {sum(b['tingkat'] == 3 for b in baris)}")


if __name__ == "__main__":
    main()
