"""Olah berkas harian dari laptop (docs/data/broker/hari/*.json) menjadi data web.

Hasil:
  docs/data/broker/indeks.json       daftar tanggal yang sudah ada
  docs/data/broker/ringkasan.json    aliran asing, akumulasi broker, beruntun, pelacak broker
  docs/data/broker/saham/<KODE>.json riwayat 10 pembeli/penjual teratas per hari
  docs/data/asing.json               transaksi asing seluruh saham dari situs IDX (bila ada)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

AKAR = cfg.KELUAR
HARI = cfg.HARI_BROKER
WIB = timezone(timedelta(hours=7))
SIMPAN = 60
TOPN = 5


def nama_broker() -> dict:
    hasil = {}
    p = Path(__file__).parent / "data" / "brokers.csv"
    if p.exists():
        baris = [b for b in p.read_text(encoding="utf-8").splitlines() if b and not b.startswith("#")]
        for r in csv.DictReader(baris):
            hasil[r["code"]] = r["name"].title()
    return hasil


def beruntun(nilai: list) -> int:
    """Jumlah hari berturut-turut dengan tanda yang sama di akhir deret (+ beli, - jual)."""
    n, tanda = 0, 0
    for v in reversed(nilai):
        if v is None or v == 0:
            break
        t = 1 if v > 0 else -1
        if tanda == 0:
            tanda = t
        if t != tanda:
            break
        n += 1
    return n * tanda


def jumlah(nilai: list, n: int):
    v = [x for x in nilai[-n:] if x is not None]
    return sum(v) if v else None


def main():
    if not HARI.exists():
        print("Belum ada data broker dari laptop.")
        return
    semua = {}
    libur = []
    for f in sorted(HARI.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("libur"):
            libur.append(d["tanggal"])
        else:
            semua[d["tanggal"]] = d
    tanggal = sorted(semua)[-SIMPAN:]
    (AKAR / "broker").mkdir(parents=True, exist_ok=True)
    (AKAR / "broker" / "indeks.json").write_text(json.dumps({
        "tanggal": sorted(semua), "libur": sorted(libur),
        "broker": sorted(t for t, d in semua.items() if d.get("saham")),
        "idx": sorted(t for t, d in semua.items() if d.get("idx")),
        "idx_lengkap": sorted(t for t, d in semua.items() if d.get("idx") and any(len(v) >= 13 for v in d["idx"].values())),
    }, separators=(",", ":")))
    if not tanggal:
        print("Belum ada hari bursa.")
        return

    kode_list = sorted({k for t in tanggal for k in semua[t]["saham"]})
    lq45 = set(cfg.kode_semesta()) | set(kode_list)  # semua saham yang dianalisis
    nama = nama_broker()
    for t in tanggal:
        for b in semua[t].get("pasar_broker") or []:
            nama.setdefault(b["kode"], b["nama"])

    # ----- per saham -----
    (AKAR / "broker" / "saham").mkdir(exist_ok=True)
    seri, metrik = {}, {}
    for kode in kode_list:
        hari = []
        fnet, top5, tval = [], [], []
        for t in tanggal:
            s = semua[t]["saham"].get(kode)
            if not s:
                fnet.append(None); top5.append(None); tval.append(None)
                continue
            hari.append({"t": t, **s})
            fnet.append(round(s["fnet"]) if s.get("fnet") is not None else None)
            tb = sum(x[3] or 0 for x in s["b"][:TOPN])
            ts = sum(x[3] or 0 for x in s["s"][:TOPN])
            top5.append(round(tb - ts))
            tval.append(round(s["tval"]) if s.get("tval") is not None else None)
        (AKAR / "broker" / "saham" / f"{kode}.json").write_text(
            json.dumps({"kode": kode, "hari": hari}, separators=(",", ":")))
        seri[kode] = {"fnet": fnet, "top5": top5, "tval": tval}
        tv5 = jumlah(tval, 5)
        metrik[kode] = {
            "fnet1": fnet[-1], "fnet5": jumlah(fnet, 5), "fnet20": jumlah(fnet, 20), "fnet60": jumlah(fnet, 60),
            "asing_beruntun": beruntun(fnet),
            "top5_1": top5[-1], "top5_5": jumlah(top5, 5), "top5_20": jumlah(top5, 20),
            "akum_beruntun": beruntun(top5),
            "rasio_akum5": round(jumlah(top5, 5) / tv5 * 100, 1) if tv5 and jumlah(top5, 5) is not None else None,
        }

    # ----- akumulasi beruntun per broker: broker yang sama membeli/menjual bersih berhari-hari -----
    beruntun_broker = []
    for kode in kode_list:
        hari = [semua[t]["saham"].get(kode) for t in tanggal]
        bersih = defaultdict(list)  # broker -> [(nilai bersih, lot bersih) per hari, None jika di luar 10 besar]
        brokers = {b[0] for h in hari if h for b in h["b"] + h["s"]}
        for h in hari:
            for br in brokers:
                if not h:
                    bersih[br].append(None)
                    continue
                bv = next((x for x in h["b"] if x[0] == br), None)
                sv = next((x for x in h["s"] if x[0] == br), None)
                if not bv and not sv:
                    bersih[br].append(None)
                else:
                    bersih[br].append(((bv[3] if bv else 0) - (sv[3] if sv else 0), (bv[2] if bv else 0) - (sv[2] if sv else 0)))
        terbaik = {}
        for br, seri_br in bersih.items():
            n = beruntun([x[0] if x else None for x in seri_br])
            if abs(n) < 2:
                continue
            potong = seri_br[-abs(n):]
            nilai = sum(x[0] for x in potong)
            lot = sum(x[1] for x in potong)
            arah = "beli" if n > 0 else "jual"
            if arah not in terbaik or abs(n) > abs(terbaik[arah]["hari"]) or (
                    abs(n) == abs(terbaik[arah]["hari"]) and abs(nilai) > abs(terbaik[arah]["nilai"])):
                terbaik[arah] = {"kode": kode, "broker": br, "hari": n, "nilai": round(nilai), "lot": round(lot),
                                 "rata": round(abs(nilai / lot / 100)) if lot else None, "sejak": tanggal[-abs(n)]}
        beruntun_broker += terbaik.values()
    beruntun_broker.sort(key=lambda x: (-abs(x["hari"]), -abs(x["nilai"])))

    # ----- pelacak broker: broker -> saham (dari daftar 10 teratas) -----
    def per_broker(daftar_tgl):
        hasil = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))  # beli val, jual val, beli lot, jual lot
        for t in daftar_tgl:
            for kode, s in semua[t]["saham"].items():
                for b in s["b"]:
                    r = hasil[b[0]][kode]; r[0] += b[3] or 0; r[2] += b[2] or 0
                for b in s["s"]:
                    r = hasil[b[0]][kode]; r[1] += b[3] or 0; r[3] += b[2] or 0
        return {br: sorted([[k, round(v[0]), round(v[1]), round(v[0] - v[1]), round(v[2]), round(v[3])]
                            for k, v in d.items()], key=lambda x: -abs(x[3]))
                for br, d in hasil.items()}

    kelas = {}
    for t in tanggal:
        for s in semua[t]["saham"].values():
            for b in s["b"] + s["s"]:
                kelas[b[0]] = b[1]

    terakhir = tanggal[-1]
    ringkasan = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "tanggal_terakhir": terakhir,
        "tanggal": tanggal,
        "seri": seri,
        "metrik": metrik,
        "broker_1h": per_broker([terakhir]),
        "broker_5h": per_broker(tanggal[-5:]),
        "broker_20h": per_broker(tanggal[-20:]),
        "pasar_broker": next((semua[t]["pasar_broker"] for t in reversed(tanggal) if semua[t].get("pasar_broker")), None),
        "pasar_broker_tanggal": next((t for t in reversed(tanggal) if semua[t].get("pasar_broker")), None),
        "nama_broker": nama,
        "beruntun_broker": beruntun_broker[:400],
        "ritel": json.loads((Path(__file__).parent / "data" / "kelas_broker.json").read_text(encoding="utf-8"))["ritel"],
        "kelas_broker": kelas,
    }
    (AKAR / "broker" / "ringkasan.json").write_text(json.dumps(ringkasan, ensure_ascii=False, separators=(",", ":")))

    # ----- transaksi asing seluruh saham dari situs IDX -----
    idx_tgl = [t for t in tanggal if semua[t].get("idx")]
    if idx_tgl:
        harian = {}
        for t in idx_tgl:
            harian[t] = {k: [v[0], v[1], v[2], v[4], v[5]] for k, v in semua[t]["idx"].items() if k in lq45}
        t = idx_tgl[-1]
        baris = []
        for k, v in semua[t]["idx"].items():
            fb, fs, close, prev, nilai, frek = v[:6]
            if nilai <= 0:
                continue
            baris.append({"kode": k, "tutup": close, "ubah_pct": round((close - prev) / prev * 100, 2) if prev else 0,
                          "nilai": nilai, "frek": frek, "asing_bersih": round((fb - fs) * close)})
        pasar = {
            "naik": sum(b["ubah_pct"] > 0 for b in baris), "turun": sum(b["ubah_pct"] < 0 for b in baris),
            "tetap": sum(b["ubah_pct"] == 0 for b in baris), "nilai_total": round(sum(b["nilai"] for b in baris)),
            "asing_bersih_total": round(sum(b["asing_bersih"] for b in baris)),
            "teratas_nilai": sorted(baris, key=lambda b: -b["nilai"])[:10],
            "asing_beli": sorted(baris, key=lambda b: -b["asing_bersih"])[:10],
            "asing_jual": sorted(baris, key=lambda b: b["asing_bersih"])[:10],
        }
        (AKAR / "asing.json").write_text(json.dumps({
            "harian": harian, "pasar": pasar, "tanggal_terakhir": t,
            "kolom": ["asing_beli_lembar", "asing_jual_lembar", "tutup", "nilai", "frekuensi"],
            "dibuat": ringkasan["dibuat"]}, ensure_ascii=False, separators=(",", ":")))

    # ----- psikologi penutupan: antrean terbaik, lot per transaksi, pasar negosiasi -----
    lengkap = [t for t in tanggal if semua[t].get("idx") and any(len(v) >= 13 for v in semua[t]["idx"].values())]
    if lengkap:
        t = lengkap[-1]
        hasil = {}
        for k, v in semua[t]["idx"].items():
            if len(v) < 13 or v[4] <= 0 or v[5] <= 0:
                continue
            close, nilai, frek = v[2], v[4], v[5]
            bid, bidv, off, offv, vol, nego = v[7:13]
            lot_trx = vol / 100 / frek
            riw = [semua[x]["idx"][k] for x in lengkap[-21:-1] if k in semua[x]["idx"] and len(semua[x]["idx"][k]) >= 13
                   and semua[x]["idx"][k][5] > 0]
            rata = sum(r[11] / 100 / r[5] for r in riw) / len(riw) if riw else None
            asing5 = sum((semua[x]["idx"][k][0] - semua[x]["idx"][k][1]) * semua[x]["idx"][k][2]
                         for x in lengkap[-5:] if k in semua[x]["idx"])
            hasil[k] = {
                "bid": bid, "bid_lot": round(bidv / 100), "offer": off, "offer_lot": round(offv / 100),
                "rasio_antrean": round(bidv / (bidv + offv), 3) if bidv + offv > 0 else None,
                "tutup_di": "offer" if off and close >= off else "bid" if bid and close <= bid else "tengah",
                "lot_per_trx": round(lot_trx, 1), "lot_per_trx_rata20": round(rata, 1) if rata else None,
                "rasio_lot": round(lot_trx / rata, 2) if rata else None,
                "nego_pct": round(nego / (nilai + nego) * 100, 1) if nilai + nego > 0 else 0,
                "asing5": round(asing5), "hari_data": len(riw) + 1,
            }
        (AKAR / "psikologi.json").write_text(json.dumps({"tanggal": t, "saham": hasil, "hari": len(lengkap)},
                                                        ensure_ascii=False, separators=(",", ":")))
        print(f"Psikologi penutupan: {len(hasil)} saham, data {t}, riwayat {len(lengkap)} hari")

    print(f"Broker: {len(tanggal)} hari ({tanggal[0]}…{terakhir}), {len(kode_list)} saham, "
          f"{len(ringkasan['broker_1h'])} broker; data IDX {len(idx_tgl)} hari.")


if __name__ == "__main__":
    main()
