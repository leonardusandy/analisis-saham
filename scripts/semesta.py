"""Susun daftar saham yang dianalisis: lapis 1 + lapis 2 + saham grup konglomerat.

Kapitalisasi = jumlah saham tercatat x harga penutupan dari data IDX kiriman laptop
(bila ada), jika belum ada memakai data fundamental atau kapitalisasi awal.
Likuiditas = rata-rata nilai transaksi 20 hari dari data IDX (bila ada).
Hasil: <DATA_KELUAR>/semesta.json
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

WIB = timezone(timedelta(hours=7))
DATA = Path(__file__).parent / "data"


def main():
    konglo = json.loads((DATA / "konglo.json").read_text(encoding="utf-8"))["grup"]
    grup_dari = {k: g for g, daftar in konglo.items() for k in daftar}
    kap = dict(json.loads((DATA / "kapitalisasi_awal.json").read_text())["kapitalisasi"])
    sumber_kap = {k: "awal" for k in kap}

    # Kapitalisasi dari data fundamental (Yahoo) bila tersedia
    fp = cfg.KELUAR / "fundamental.json"
    if fp.exists():
        for s in json.loads(fp.read_text())["saham"]:
            if s.get("kapitalisasi"):
                kap[s["kode"]] = s["kapitalisasi"]
                sumber_kap[s["kode"]] = "yahoo"

    # Data IDX dari laptop: nilai transaksi 20 hari dan jumlah saham tercatat
    nilai = {}
    hari = sorted(cfg.HARI_BROKER.glob("*.json"))[-20:] if cfg.HARI_BROKER.exists() else []
    idx_hari = []
    for f in hari:
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("idx"):
            idx_hari.append(d["idx"])
    if idx_hari:
        semua = set().union(*idx_hari)
        for k in semua:
            nilai[k] = statistics.mean([h.get(k, [0] * 6)[4] for h in idx_hari])
        for k, v in idx_hari[-1].items():
            if len(v) > 6 and v[6] and v[2]:  # jumlah saham tercatat x harga penutupan
                kap[k] = v[6] * v[2]
                sumber_kap[k] = "idx"

    hasil = []
    for k in sorted(set(kap) | set(grup_dari) | set(cfg.SAHAM)):
        kp = kap.get(k) or 0
        lapis = 1 if kp >= cfg.BATAS_LAPIS1 else 2 if kp >= cfg.BATAS_LAPIS2 else 3
        masuk = lapis <= 2 or k in grup_dari or k in cfg.SAHAM
        if not masuk:
            continue
        n = nilai.get(k)
        hasil.append({
            "kode": k, "kap": round(kp) if kp else None, "lapis": lapis, "grup": grup_dari.get(k),
            "lq45": k in cfg.SAHAM,
            "nilai20": round(n) if n is not None else None,
            # Tanpa data IDX, keputusan likuid ditunda ke analisis harga (nilai transaksi dari Yahoo)
            "likuid": (n >= cfg.NILAI_TRANSAKSI_MINIMAL) if n is not None else None,
        })
    data = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "sumber_kapitalisasi": {s: sum(1 for x in hasil if sumber_kap.get(x["kode"]) == s) for s in ["idx", "yahoo", "awal"]},
        "saham": hasil,
    }
    cfg.KELUAR.mkdir(parents=True, exist_ok=True)
    (cfg.KELUAR / "semesta.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    l = [x["lapis"] for x in hasil]
    print(f"Semesta: {len(hasil)} saham (lapis1 {l.count(1)}, lapis2 {l.count(2)}, lapis3-konglo {l.count(3)}); "
          f"likuid {sum(1 for x in hasil if x['likuid'])}; kapitalisasi {data['sumber_kapitalisasi']}")


if __name__ == "__main__":
    main()
