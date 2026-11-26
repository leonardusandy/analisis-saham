"""Pengumpul data harian yang dijalankan di laptop Anda.

Mengambil dari situs yang memblokir server GitHub:
  * Ringkasan broker per saham (10 pembeli & 10 penjual terbesar) dan nilai bersih
    asing dari Indo Premier (IPOT), halaman publik tanpa login.
  * Peringkat broker seluruh pasar hari ini (IPOT).
  * Ringkasan Saham dari situs IDX (transaksi asing seluruh saham), bila bisa diakses.
Hasilnya diunggah ke repositori GitHub Anda sebagai satu commit:
  docs/data/broker/hari/YYYY-MM-DD.json
GitHub kemudian mengolahnya otomatis menjadi data untuk web.

Pemakaian:
  python kumpul_lokal.py            # ambil hari bursa yang belum ada (maks 20 hari ke belakang)
  python kumpul_lokal.py --uji      # uji pengurai memakai contoh HTML, tanpa internet/unggah
  python kumpul_lokal.py --tanpa-unggah   # ambil data, simpan di folder 'keluaran' saja
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = "leonardusandy/analisis-saham"
CABANG = "main"
WIB = timezone(timedelta(hours=7))
FOLDER = Path(__file__).resolve().parent
BERKAS_TOKEN = Path.home() / ".analisis-saham-token.txt"
HARI_MUNDUR = 20
AGEN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

IPOT_BROKER = "https://www.indopremier.com/module/saham/include/data-brokersummary.php"
IPOT_TOPBROKER = "https://www.indopremier.com/module/saham/include/ma-topbroker.php"
IDX_RINGKASAN = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0&date={}"

KELAS = {"text-foreign": "A", "text-local": "L", "text-bumn": "B"}  # Asing, Lokal, BUMN


def log(*a):
    print(datetime.now(WIB).strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------------------
# Pengurai angka & HTML IPOT
# ---------------------------------------------------------------------------
def angka(teks: str) -> float | None:
    """'352.5 B' -> 3.525e11 ; '687,161 ' -> 687161 ; '-264.04 B' ; '2.0 M' ; '1.0 T'."""
    t = (teks or "").replace("&nbsp;", " ").strip()
    if not t or t == "-":
        return None
    m = re.fullmatch(r"(-?[\d.,]+)\s*([KMBT]?)", t)
    if not m:
        return None
    n, s = m.groups()
    if s:
        n = float(n.replace(",", ""))
        return n * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s]
    return float(n.replace(",", ""))


def sel(td: str) -> tuple[str, str | None]:
    """Isi teks dan kelas span dari satu <td>."""
    kls = re.search(r'class="(text-[a-z]+)"', td)
    teks = re.sub(r"<[^>]+>", "", td).replace("&nbsp;", " ").strip()
    return teks, (kls.group(1) if kls else None)


def urai_broker(html: str) -> dict | None:
    if "Invalid stock code" in html:
        return None
    tbody = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    beli, jual = [], []
    if tbody:
        for tr in re.findall(r"<tr>(.*?)</tr>", tbody.group(1), re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 9:
                continue
            c = [sel(td) for td in tds]
            if c[0][0]:
                beli.append([c[0][0], KELAS.get(c[0][1], "L"), angka(c[1][0]), angka(c[2][0]), angka(c[3][0])])
            if c[5][0]:
                jual.append([c[5][0], KELAS.get(c[5][1], "L"), angka(c[6][0]), angka(c[7][0]), angka(c[8][0])])
    kaki = {}
    for nama, isi in re.findall(r"(T\. Val|F\. NVal|T\.Lot|Avg)\s*:\s*([^<]+)<", html):
        kaki[nama] = angka(isi)
    return {
        "b": beli, "s": jual,
        "tval": kaki.get("T. Val"), "fnet": kaki.get("F. NVal"),
        "tlot": kaki.get("T.Lot"), "avg": kaki.get("Avg"),
    }


def urai_topbroker(html: str) -> list:
    tbody = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    hasil = []
    if not tbody:
        return hasil
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody.group(1), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 9:
            continue
        c = [sel(td) for td in tds]
        hasil.append({
            "kode": c[1][0], "kelas": KELAS.get(c[1][1], "L"), "nama": c[2][0],
            "tval": angka(c[3][0]), "nval": angka(c[4][0]), "bval": angka(c[5][0]),
            "sval": angka(c[6][0]), "tvol": angka(c[7][0]), "freq": angka(c[8][0]),
        })
    return hasil


# ---------------------------------------------------------------------------
# Jaringan
# ---------------------------------------------------------------------------
_SESI = None


def sesi():
    global _SESI
    if _SESI is None:
        try:
            from curl_cffi import requests as creq  # meniru Chrome, lebih jarang diblokir

            _SESI = creq.Session(impersonate="chrome")
        except ImportError:
            import requests

            _SESI = requests.Session()
            _SESI.headers["User-Agent"] = AGEN
    return _SESI


def ambil(url: str, coba: int = 4) -> str | None:
    jeda = 0.5
    for i in range(coba):
        try:
            r = sesi().get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            # IPOT kadang memberi 404 palsu beberapa detik; ulangi
        except Exception as e:  # noqa: BLE001
            if i == coba - 1:
                log("  ! gagal:", url[:90], e)
        time.sleep(jeda)
        jeda *= 2
    return None


def daftar_saham() -> list[str]:
    import requests

    url = f"https://raw.githubusercontent.com/{REPO}/{CABANG}/docs/data/ringkasan.json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return [s["kode"] for s in r.json()["saham"]]


def tanggal_tersedia() -> set[str]:
    import requests

    url = f"https://raw.githubusercontent.com/{REPO}/{CABANG}/docs/data/broker/indeks.json"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            d = r.json()
            return set(d.get("tanggal", [])) | set(d.get("libur", []))
    except Exception:  # noqa: BLE001
        pass
    return set()


def hari_bursa_terakhir(n: int) -> list[date]:
    kini = datetime.now(WIB)
    d = kini.date()
    # Sebelum 16.30 WIB data hari ini belum final
    if kini.hour * 60 + kini.minute < 16 * 60 + 30:
        d -= timedelta(days=1)
    hasil = []
    while len(hasil) < n:
        if d.weekday() < 5:
            hasil.append(d)
        d -= timedelta(days=1)
    return sorted(hasil)


def ambil_hari(tgl: date, kode_list: list[str], terbaru: bool) -> dict:
    s = tgl.strftime("%m/%d/%Y")
    data = {"tanggal": tgl.isoformat(), "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "saham": {}}
    ada_transaksi = False
    for i, kode in enumerate(kode_list, 1):
        html = ambil(f"{IPOT_BROKER}?code={kode}&start={s}&end={s}&fd=all&board=all")
        if html is None:
            continue
        hasil = urai_broker(html)
        if hasil is None:
            continue
        if hasil["b"] or (hasil["tval"] or 0) > 0:
            ada_transaksi = True
            data["saham"][kode] = hasil
        if i % 10 == 0:
            log(f"  {tgl} {i}/{len(kode_list)} saham")
        time.sleep(0.4)
        if i == 3 and not ada_transaksi:
            break  # hari libur bursa: tiga saham teramai pun tanpa transaksi
    data["libur"] = not ada_transaksi
    if terbaru and ada_transaksi:
        html = ambil(IPOT_TOPBROKER)
        if html:
            data["pasar_broker"] = urai_topbroker(html)
        data["idx"] = ambil_idx(tgl)
    return data


def ambil_idx(tgl: date) -> dict | None:
    """Ringkasan Saham IDX (seluruh saham). Sering diblokir; tidak wajib."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return None
    try:
        s = creq.Session(impersonate="chrome")
        s.get("https://www.idx.co.id/id", timeout=30)
        r = s.get(IDX_RINGKASAN.format(tgl.strftime("%Y%m%d")), timeout=40,
                  headers={"Referer": "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/"})
        if r.status_code != 200:
            log(f"  Situs IDX menolak ({r.status_code}); dilewati.")
            return None
        hasil = {}
        for d in r.json().get("data") or []:
            hasil[d["StockCode"]] = [
                float(d.get("ForeignBuy") or 0), float(d.get("ForeignSell") or 0),
                float(d.get("Close") or 0), float(d.get("Previous") or 0),
                float(d.get("Value") or 0), int(d.get("Frequency") or 0),
            ]
        log(f"  Situs IDX: {len(hasil)} saham.")
        return hasil or None
    except Exception as e:  # noqa: BLE001
        log("  Situs IDX tidak bisa diakses:", e)
        return None


# ---------------------------------------------------------------------------
# Unggah ke GitHub (satu commit untuk semua berkas)
# ---------------------------------------------------------------------------
def unggah(berkas: dict[str, str], pesan: str) -> None:
    import requests

    token = os.environ.get("GITHUB_TOKEN") or (BERKAS_TOKEN.read_text().strip() if BERKAS_TOKEN.exists() else "")
    if not token:
        raise SystemExit(f"Token GitHub tidak ditemukan. Jalankan pemasang lagi atau simpan token di {BERKAS_TOKEN}")
    api = f"https://api.github.com/repos/{REPO}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    for coba in range(4):
        ref = requests.get(f"{api}/git/ref/heads/{CABANG}", headers=h, timeout=30)
        ref.raise_for_status()
        induk = ref.json()["object"]["sha"]
        pohon_induk = requests.get(f"{api}/git/commits/{induk}", headers=h, timeout=30).json()["tree"]["sha"]
        entri = []
        for jalur, isi in berkas.items():
            blob = requests.post(f"{api}/git/blobs", headers=h, timeout=60,
                                 json={"content": base64.b64encode(isi.encode()).decode(), "encoding": "base64"})
            blob.raise_for_status()
            entri.append({"path": jalur, "mode": "100644", "type": "blob", "sha": blob.json()["sha"]})
        pohon = requests.post(f"{api}/git/trees", headers=h, timeout=60, json={"base_tree": pohon_induk, "tree": entri})
        pohon.raise_for_status()
        komit = requests.post(f"{api}/git/commits", headers=h, timeout=30,
                              json={"message": pesan, "tree": pohon.json()["sha"], "parents": [induk]})
        komit.raise_for_status()
        upd = requests.patch(f"{api}/git/refs/heads/{CABANG}", headers=h, timeout=30,
                             json={"sha": komit.json()["sha"], "force": False})
        if upd.status_code == 200:
            log(f"Terunggah: {len(berkas)} berkas.")
            return
        log(f"  Repositori sedang diperbarui pihak lain ({upd.status_code}); mencoba lagi…")
        time.sleep(5 * (coba + 1))
    raise SystemExit("Gagal mengunggah setelah beberapa percobaan.")


# ---------------------------------------------------------------------------
def uji():
    contoh = FOLDER / "contoh"
    b = urai_broker((contoh / "brokersummary_bbca_20261106.html").read_text())
    assert b["b"][0][:2] == ["KZ", "A"] and b["b"][0][2] == 687161 and abs(b["b"][0][3] - 352.5e9) < 1, b["b"][0]
    assert b["s"][0][:2] == ["CC", "B"], b["s"][0]
    assert len(b["b"]) == 10 and len(b["s"]) == 10
    assert abs(b["fnet"] - 219.0e9) < 1 and abs(b["tval"] - 1.0e12) < 1 and b["avg"] == 5108, b
    kosong = urai_broker((contoh / "brokersummary_bbca_20261017_no_trades.html").read_text())
    assert not kosong["b"] and not (kosong["tval"] or 0), kosong
    t = urai_topbroker((contoh / "topbroker_20261106.html").read_text())
    assert t[0]["kode"] == "CP" and abs(t[0]["tval"] - 2.79e12) < 1e6 and abs(t[2]["nval"] + 264.04e9) < 1e6, t[:3]
    print(f"Uji pengurai lulus: {len(b['b'])} pembeli, {len(b['s'])} penjual, {len(t)} broker pasar.")


def main():
    if "--uji" in sys.argv:
        uji()
        return
    log("Mulai mengumpulkan data…")
    kode_list = daftar_saham()
    sudah = tanggal_tersedia()
    hari = [d for d in hari_bursa_terakhir(HARI_MUNDUR) if d.isoformat() not in sudah]
    if not hari:
        log("Semua hari bursa terakhir sudah ada. Selesai.")
        return
    log(f"{len(kode_list)} saham, {len(hari)} hari akan diambil: {hari[0]} … {hari[-1]}")
    berkas = {}
    for tgl in hari:
        d = ambil_hari(tgl, kode_list, terbaru=(tgl == hari[-1]))
        log(f"{tgl}: {'libur bursa' if d['libur'] else str(len(d['saham'])) + ' saham'}")
        berkas[f"docs/data/broker/hari/{tgl.isoformat()}.json"] = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    if "--tanpa-unggah" in sys.argv:
        out = FOLDER / "keluaran"
        out.mkdir(exist_ok=True)
        for jalur, isi in berkas.items():
            (out / Path(jalur).name).write_text(isi, encoding="utf-8")
        log(f"Disimpan di {out}")
        return
    unggah(berkas, f"Data broker {hari[0]}…{hari[-1]} (laptop)")
    log("Selesai. Web akan diperbarui GitHub dalam beberapa menit.")


if __name__ == "__main__":
    main()
