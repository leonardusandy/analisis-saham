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
  Warna     : Baru masuk (status berlangsung <= 2 hari), Sinyal beli (pilihan utama strategi B),
              Naik/turun pangkat (tingkat berubah dari kemarin).
  Strategi B: pilihan utama web (scripts/strategi.py). Saham layak dengan kenaikan 20 hari <= 100%,
              diurutkan dengan peringkat kenaikan 20 hari + peringkat model antarsaham. Uji Jan 2024 -
              Nov 2026 (semesta bebas bias): rata-rata +0,60% per transaksi, menang 49%, untung/rugi 1,41.
  Analisa   : 3 pilihan utama + 2 cadangan strategi B, tanpa tanda bahaya fundamental. Entry = harga
              penutupan s.d. 0,5 ATR di bawahnya; CL = 5% di bawah harga beli; jual paling lambat penutupan
              hari ke-3 setelah beli; R1/R2 = resistance terdekat sebagai acuan.
  Pasar     : beli hanya saat IHSG di atas MA20. Jika tidak, analisa ditampilkan sebagai "ditunda".
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
    STR = {}
    p_str = cfg.KELUAR / "strategi.json"
    if p_str.exists():
        STR = json.loads(p_str.read_text())
    pilihan = {x["kode"]: x for x in STR.get("B", [])}
    pilihan_utama = {x["kode"] for x in STR.get("B", []) if x.get("utama")}
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
        if (st not in ("up", "side") and kode not in pilihan) or not s.get("likuid"):
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
        sinyal = kode in pilihan_utama  # pilihan utama strategi B (lihat scripts/strategi.py)
        lama = tanggal_mulai(hs["st"])
        warna = ("baru" if lama <= 2 else "beli" if sinyal else "naik" if tk > tk_k and st == st_k
                 else "turun" if tk < tk_k and st == st_k else None)
        baris.append({
            "kode": kode, "nama": f.get("nama"), "sektor": sektor, "sk": KODE_SEKTOR.get(sektor, ""),
            "lapis": s.get("lapis"), "grup": s.get("grup"), "status": st, "tingkat": tk,
            "support": bulatkan(support, "bawah"), "resistance": bulatkan(r1, "atas"), "r2": bulatkan(r2, "atas"),
            "kuat": sentuh >= 3, "murah": murah, "sejak": df.index[-lama], "hari": lama,
            "warna": warna, "sinyal": sinyal, "tutup": c, "ubah": s.get("perubahan_pct"), "atr": round(float(atr), 1),
            "ma10": round(float(df["c"].tail(10).mean()), 1),
            "skor": s.get("skor"), "rasio_vol": rv, "macd": bool(s.get("sinyal_macd")),
            "bahaya": f.get("bahaya") or [], "kualitas": bool(f.get("lolos_kualitas")),
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

    # ----- analisa harian: pilihan strategi B (utama + cadangan), urutan sesuai skor -----
    per_kode = {b["kode"]: b for b in baris}
    kand = [per_kode[x["kode"]] for x in STR.get("B", []) if x["kode"] in per_kode and not per_kode[x["kode"]]["bahaya"]]
    analisa = []
    for b in kand:
        sx = pilihan[b["kode"]]
        lo = bulatkan(max(b["support"], b["tutup"] - 0.5 * b["atr"]), "bawah")
        hi = bulatkan(b["tutup"], "bawah")
        r1 = b["resistance"] if b["resistance"] > hi * 1.01 else bulatkan(hi + b["atr"], "atas")
        r2 = b["r2"] if b["r2"] > r1 * 1.01 else bulatkan(r1 + b["atr"], "atas")
        cl = bulatkan(hi * (1 - cfg.STOP_PERSEN), "atas")  # batas rugi 5% dari harga beli, sesuai uji
        t3 = bulatkan(hi + 3 * (hi - cl), "atas")  # sasaran minimal rasio 1:3 (acuan, bukan perintah jual)
        untung, rugi = r1 / hi - 1, 1 - cl / hi
        analisa.append({
            "kode": b["kode"], "sk": b["sk"], "status": b["status"], "tingkat": b["tingkat"],
            "entry": [lo, hi], "r1": r1, "r2": r2, "cl": cl, "t3": t3, "ma10": b["ma10"],
            "untung_r1_pct": round(untung * 100, 1), "rugi_cl_pct": round(-rugi * 100, 1), "rasio": round(untung / rugi, 2),
            "macd": b["macd"], "kualitas": b["kualitas"], "utama": sx["utama"], "urutan": sx["urutan"],
            "alasan": f"naik {sx['r20']:+.0f}% dalam 20 hari (peringkat {sx['pk_r20']:.0f}), model peringkat {sx['pk_model']:.0f}"
                      + (", tanpa jejak distribusi" if not sx["distribusi"] else ", ada jejak distribusi")
                      + (", sektor sedang menguat" if b["sektor"] in lebih_baik else "")
                      + (", lolos saringan kualitas" if b["kualitas"] else ""),
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
        "pasar_mendukung": bool(STR.get("pasar_mendukung", rk.get("pasar_mendukung", True))),
        "aturan": __doc__.split("ATURAN (juga ditampilkan di web):")[1].strip(),
    }
    (k / "stockpick.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str))
    print(f"Stockpick: uptrend {len(data['uptrend'])}, sideways {len(data['sideways'])}, keluar {len(keluar)}, "
          f"analisa {len(analisa)}, sektor better {len(lebih_baik)}, support kuat {sum(b['kuat'] for b in baris)}, "
          f"murah {sum(b['murah'] for b in baris)}, ^^^ {sum(b['tingkat'] == 3 for b in baris)}")


if __name__ == "__main__":
    main()
