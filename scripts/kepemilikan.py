"""Struktur kepemilikan (pemegang saham >= 1%) dan perubahannya antarbulan.

Sumber: daftar pemegang saham di atas 1% dari KSEI yang dipublikasikan BEI setiap
bulan, diambil dari salinan berkas aslinya di rilis GitHub proyek fzn0x/idx
(situs IDX memblokir server GitHub).
Hasil: docs/data/kepemilikan.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg  # noqa: E402

DASAR = "https://github.com/fzn0x/idx/releases/download/ownership-data/"
BERKAS = Path(__file__).resolve().parent.parent / "docs" / "data" / "kepemilikan.json"
WIB = timezone(timedelta(hours=7))
JENIS = {
    "CORPORATE": "Korporasi", "INDIVIDUAL": "Perorangan", "INSURANCE": "Asuransi",
    "PENSION FUNDS": "Dana pensiun", "MUTUAL FUNDS": "Reksa dana", "FINANCIAL INSTITUTIONAL": "Lembaga keuangan",
    "SECURITIES COMPANY": "Perusahaan efek", "FOUNDATION": "Yayasan", "OTHERS": "Lainnya",
    "INVESTMENT ADVISORS": "Penasihat investasi", "PRIVATE BANK": "Bank swasta", "PRIVATE EQUITY": "Ekuitas swasta",
    "FIRM": "Perusahaan", "BANK": "Bank", "STATE OWNED ENTERPRISES": "BUMN", "STATE OWNED COMPANY": "BUMN",
    "INVESTMENT MANAGER": "Manajer investasi", "VENTURE CAPITAL": "Modal ventura",
    "SOVEREIGN WEALTH FUND": "Dana kekayaan negara", "HEDGE FUND": "Dana lindung nilai",
    "GOVERNMENT": "Pemerintah", "EXCHANGE TRADED FUNDS": "Reksa dana ETF", "TRUSTEE BANK": "Bank kustodian",
}
BUANG = {"PT", "PERSERO", "PERUSAHAAN", "PERSEROAN", "TBK", "THE", "LTD", "LIMITED", "INC", "CO", "CORP", "LLC", "TBK."}


def kunci_nama(r: dict) -> str:
    import re

    teks = (r.get("entity_key") or r.get("holder") or "").upper()
    kata = [k for k in re.split(r"[^A-Z0-9]+", teks) if k and k not in BUANG]
    return " ".join(kata)
STATUS = {"CONTROLLER": "Pengendali", "AFFILIATE OF THE CONTROLLER": "Afiliasi pengendali"}


def unduh(nama: str) -> bytes:
    req = urllib.request.Request(DASAR + nama, headers={"User-Agent": "analisis-saham"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def baca_rilis(rilis: dict) -> list[dict]:
    baris = []
    for bagian in rilis["parts"]:
        isi = unduh(bagian["file"])
        if hashlib.sha256(isi).hexdigest() != bagian["sha256"]:
            raise RuntimeError(f"Hash tidak cocok: {bagian['file']}")
        baris += [r for r in json.loads(isi) if r.get("symbol") in cfg.SAHAM]
    return baris


def ringkas(r: dict) -> dict:
    return {
        "nama": r.get("holder") or r.get("entity_key"),
        "kunci": r.get("entity_key") or r.get("holder"),
        "jenis": JENIS.get(r.get("investor_type"), (r.get("investor_type") or "").title()),
        "asal": {"A": "Asing", "F": "Asing", "L": "Lokal"}.get(r.get("local_foreign"), "–"),
        "lembar": r.get("shares_total"),
        "persen": r.get("pct"),
        "status": STATUS.get(r.get("controller_or_affiliate")),
    }


def main():
    indeks = json.loads(unduh("index.json"))
    rilis = sorted(indeks["releases"], key=lambda r: r["as_of"], reverse=True)[:2]
    if not rilis:
        print("Tidak ada rilis kepemilikan.")
        return
    kini = baca_rilis(rilis[0])
    lalu = baca_rilis(rilis[1]) if len(rilis) > 1 else []

    def per_saham(baris):
        d = {}
        for r in baris:
            d.setdefault(r["symbol"], {})[kunci_nama(r)] = ringkas(r)
        return d

    pk, pl = per_saham(kini), per_saham(lalu)
    saham, perubahan = {}, []
    for kode in cfg.SAHAM:
        a, b = pk.get(kode, {}), pl.get(kode, {})
        daftar = []
        for kunci, h in a.items():
            sebelum = b.get(kunci)
            h = dict(h)
            h["persen_lalu"] = sebelum["persen"] if sebelum else None
            h["lembar_lalu"] = sebelum["lembar"] if sebelum else None
            h["ubah_lembar"] = (h["lembar"] or 0) - (sebelum["lembar"] or 0) if sebelum else h["lembar"]
            h["baru"] = sebelum is None and bool(b)
            daftar.append(h)
        for kunci, h in b.items():
            if kunci not in a:
                daftar.append({**h, "persen_lalu": h["persen"], "lembar_lalu": h["lembar"], "persen": None,
                               "lembar": None, "ubah_lembar": -(h["lembar"] or 0), "keluar": True})
        daftar.sort(key=lambda h: -(h["persen"] if h["persen"] is not None else -1))
        terdata = sum(h["persen"] or 0 for h in daftar if not h.get("keluar"))
        saham[kode] = {
            "pemegang": daftar,
            "persen_terdata": round(terdata, 2),
            "pengendali": round(sum(h["persen"] or 0 for h in daftar if h.get("status") and not h.get("keluar")), 2),
            "asing": round(sum(h["persen"] or 0 for h in daftar if h["asal"] == "Asing" and not h.get("keluar")), 2),
        }
        for h in daftar:
            if b and (h.get("baru") or h.get("keluar") or (h["ubah_lembar"] or 0) != 0):
                perubahan.append({"kode": kode, **{k: h.get(k) for k in
                                  ["nama", "jenis", "asal", "status", "persen", "persen_lalu", "ubah_lembar", "baru", "keluar"]}})

    perubahan.sort(key=lambda p: -abs((p["persen"] or 0) - (p["persen_lalu"] or 0)))
    data = {
        "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "per_tanggal": rilis[0]["as_of"],
        "pembanding": rilis[1]["as_of"] if len(rilis) > 1 else None,
        "sumber": rilis[0].get("source_url"),
        "saham": saham,
        "perubahan": perubahan[:300],
    }
    BERKAS.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"Kepemilikan per {data['per_tanggal']}: {len(saham)} saham, {len(perubahan)} perubahan.")


if __name__ == "__main__":
    main()
