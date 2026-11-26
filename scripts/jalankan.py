"""Ambil data harian saham, analisis, dan simpan JSON untuk halaman web.

Pemakaian:
    python scripts/jalankan.py           # ambil data asli dari Yahoo Finance
    python scripts/jalankan.py --contoh  # pakai data acak (untuk uji tanpa internet)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402
from analisis import analisis_saham, tambah_indikator  # noqa: E402

FOLDER_DATA = cfg.KELUAR
WIB = timezone(timedelta(hours=7))


# ---------------------------------------------------------------------------
# Sumber data
# ---------------------------------------------------------------------------
def ambil_yahoo(kode_list: list[str]) -> dict[str, pd.DataFrame]:
    import time

    import yfinance as yf

    simbol = [f"{k}.JK" for k in kode_list] + [cfg.KODE_IHSG]
    hasil = {}

    def simpan(s, df):
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
        if df.empty:
            return False
        df.index = pd.to_datetime(df.index).tz_localize(None)
        kode = "IHSG" if s == cfg.KODE_IHSG else s.replace(".JK", "")
        hasil[kode] = df
        return True

    # 1) unduh per kelompok 100 saham
    for i in range(0, len(simbol), 100):
        kelompok = simbol[i:i + 100]
        try:
            mentah = yf.download(
                kelompok, period=cfg.PERIODE, interval="1d", auto_adjust=False,
                group_by="ticker", threads=True, progress=False,
            )
            for s in kelompok:
                try:
                    simpan(s, mentah[s])
                except KeyError:
                    pass
        except Exception as e:  # noqa: BLE001
            print("  ! unduhan kelompok gagal:", e)
        time.sleep(2)

    # 2) ulangi satu per satu untuk yang gagal
    for s in simbol:
        kode = "IHSG" if s == cfg.KODE_IHSG else s.replace(".JK", "")
        if kode in hasil:
            continue
        for coba in range(3):
            try:
                df = yf.Ticker(s).history(period=cfg.PERIODE, interval="1d", auto_adjust=False)
                if simpan(s, df):
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  ! {s} percobaan {coba + 1}: {e}")
            time.sleep(3)
        else:
            print(f"  ! {s}: tidak ada data")
    return hasil


def data_contoh(kode_list: list[str]) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    tanggal = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=500)
    hasil = {}
    for kode in kode_list + ["IHSG"]:
        awal = rng.uniform(300, 9000) if kode != "IHSG" else 7200
        langkah = rng.normal(0.0004, 0.02 if kode != "IHSG" else 0.009, len(tanggal))
        c = awal * np.exp(np.cumsum(langkah))
        o = c * (1 + rng.normal(0, 0.006, len(c)))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, len(c))))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, len(c))))
        v = rng.lognormal(17.5, 0.5, len(c))
        hasil[kode] = pd.DataFrame(
            {"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=tanggal
        )
    return hasil


# ---------------------------------------------------------------------------
# Utama
# ---------------------------------------------------------------------------
def main() -> None:
    contoh = "--contoh" in sys.argv
    semesta = {s["kode"]: s for s in cfg.semesta()}
    SAHAM = list(semesta)
    print(f"Mengambil data {len(SAHAM)} saham", "(CONTOH)" if contoh else "dari Yahoo Finance", "...")
    data = data_contoh(SAHAM) if contoh else ambil_yahoo(SAHAM)

    (FOLDER_DATA / "saham").mkdir(parents=True, exist_ok=True)
    semua = []

    gagal = []
    for kode in SAHAM:
        if kode not in data:
            gagal.append(kode)
            continue
        out = analisis_saham(kode, data[kode])
        if out is None:
            gagal.append(kode)
            continue
        ringkas, detail = out
        info = semesta[kode]
        ringkas.update({"lapis": info.get("lapis"), "grup": info.get("grup"), "kap": info.get("kap"), "lq45": info.get("lq45")})
        if info.get("likuid") is not None:  # likuiditas dari data IDX 20 hari lebih akurat
            ringkas["likuid"] = bool(info["likuid"])
        detail["ringkas"] = ringkas
        semua.append(ringkas)
        with open(FOLDER_DATA / "saham" / f"{kode}.json", "w") as f:
            json.dump(detail, f, separators=(",", ":"))

    if not semua:
        raise SystemExit("Tidak ada data saham yang berhasil diambil.")

    # IHSG
    ihsg = None
    if "IHSG" in data and len(data["IHSG"]) > 60:
        d = tambah_indikator(data["IHSG"].dropna(subset=["Close"]))
        akhir = d.iloc[-1]
        ihsg = {
            "tanggal": d.index[-1].strftime("%Y-%m-%d"),
            "tutup": round(float(akhir["Close"]), 2),
            "perubahan_pct": round(float(akhir["PERUBAHAN"]), 2),
            "rsi": round(float(akhir["RSI"]), 1),
            "di_atas_ma20": bool(akhir["Close"] > akhir["SMA20"]),
            "di_atas_ma50": bool(akhir["Close"] > akhir["SMA50"]),
            "riwayat": [
                {"t": i.strftime("%Y-%m-%d"), "c": round(float(v), 2)}
                for i, v in d["Close"].tail(120).items()
            ],
        }

    # Uji balik gabungan (rata-rata seluruh saham)
    gabungan = {
        "jumlah": sum(s["uji_balik"].get("jumlah", 0) for s in semua),
    }
    if gabungan["jumlah"]:
        bobot = [(s["uji_balik"]["jumlah"], s["uji_balik"]) for s in semua if s["uji_balik"].get("jumlah")]
        n = gabungan["jumlah"]
        gabungan["persen_menang"] = round(sum(w * u["persen_menang"] for w, u in bobot) / n, 1)
        gabungan["rata_hasil_pct"] = round(sum(w * u["rata_hasil_pct"] for w, u in bobot) / n, 2)
        gabungan["kena_target"] = sum(u["kena_target"] for _, u in bobot)
        gabungan["kena_stop"] = sum(u["kena_stop"] for _, u in bobot)
        gabungan["habis_waktu"] = sum(u["habis_waktu"] for _, u in bobot)

    tanggal_data = max(s["tanggal"] for s in semua)
    # saringan pengaman fundamental (dari data fundamental terakhir, jika ada)
    bahaya = {}
    p_fund = FOLDER_DATA / "fundamental.json"
    if p_fund.exists():
        for f in json.loads(p_fund.read_text()).get("saham", []):
            if f.get("bahaya"):
                bahaya[f["kode"]] = f["bahaya"]
    kandidat = sorted(
        [s for s in semua if s.get("sinyal_j") and s["likuid"] and s["tanggal"] == tanggal_data
         and s["kode"] not in bahaya],
        key=lambda s: (s["sinyal_macd"], s["skor"], s["rasio_vol"] or 0),
        reverse=True,
    )
    pasar_mendukung = bool(ihsg and ihsg["di_atas_ma20"])
    kandidat_tunda = [] if pasar_mendukung else kandidat
    if not pasar_mendukung:
        kandidat = []
    tersaring = [s["kode"] for s in semua if s.get("sinyal_j") and s["likuid"] and s["kode"] in bahaya]
    terkini = [s for s in semua if s["tanggal"] == tanggal_data and s["perubahan_pct"] is not None]
    naik = sorted(terkini, key=lambda s: s["perubahan_pct"], reverse=True)[:5]
    turun = sorted(terkini, key=lambda s: s["perubahan_pct"])[:5]

    ringkasan = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "tanggal_data": tanggal_data,
        "data_contoh": contoh,
        "pengaturan": {
            "biaya_beli": cfg.BIAYA_BELI,
            "biaya_jual": cfg.BIAYA_JUAL,
            "stop_persen": cfg.STOP_PERSEN,
            "kali_atr_target": cfg.KALI_ATR_TARGET_ACUAN,
            "skor_minimal": cfg.SKOR_MINIMAL,
            "hari_pegang_maks": cfg.HARI_PEGANG_MAKS,
            "nilai_transaksi_minimal_miliar": cfg.NILAI_TRANSAKSI_MINIMAL / 1e9,
        },
        "ihsg": ihsg,
        "kandidat": [s["kode"] for s in kandidat],
        "kandidat_tunda": [s["kode"] for s in kandidat_tunda],
        "kandidat_tersaring": [{"kode": k, "alasan": bahaya[k]} for k in tersaring],
        "pasar_mendukung": pasar_mendukung,
        "naik_terbesar": [s["kode"] for s in naik],
        "turun_terbesar": [s["kode"] for s in turun],
        "uji_balik_gabungan": gabungan,
        "saham": semua,
    }
    with open(FOLDER_DATA / "ringkasan.json", "w") as f:
        json.dump(ringkasan, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Selesai: {len(semua)} saham, {len(kandidat)} kandidat, data {tanggal_data}. Tanpa data: {len(gagal)} {gagal[:20]}")


if __name__ == "__main__":
    main()
