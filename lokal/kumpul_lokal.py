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
SITUS = "https://leonardusandy.github.io/analisis-saham/"
HARI_BROKER_PENUH = 5   # ringkasan broker semua saham ramai untuk 5 hari terakhir; hari lebih lama hanya LQ45
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
GAGAL_TERAKHIR = ""


def sesi():
    global _SESI
    if _SESI is None:
        import requests

        _SESI = requests.Session()
        _SESI.headers.update({
            "User-Agent": AGEN,
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
            "Referer": "https://www.indopremier.com/ipotnews/",
            "X-Requested-With": "XMLHttpRequest",
        })
    return _SESI


def ambil(url: str, coba: int = 3) -> str | None:
    global GAGAL_TERAKHIR
    jeda = 0.5
    for _ in range(coba):
        try:
            r = sesi().get(url, timeout=(10, 20))
            if r.status_code == 200:
                return r.text
            GAGAL_TERAKHIR = f"status {r.status_code}"  # IPOT kadang memberi 404 palsu sesaat; ulangi
        except Exception as e:  # noqa: BLE001
            GAGAL_TERAKHIR = f"{type(e).__name__}: {str(e)[:120]}"
        time.sleep(jeda)
        jeda *= 2
    log(f"  ! gagal mengambil ({GAGAL_TERAKHIR})")
    return None


def daftar_saham() -> tuple[list[str], list[str]]:
    """(saham ramai untuk ringkasan broker, saham LQ45) dari situs web Anda."""
    import requests

    try:
        r = requests.get(SITUS + "data/semesta.json", timeout=30)
        r.raise_for_status()
        sm = r.json()["saham"]
        ramai = [x["kode"] for x in sm if x.get("likuid") or (x.get("likuid") is None and x.get("lq45"))]
        lq45 = [x["kode"] for x in sm if x.get("lq45")]
        return ramai, lq45
    except Exception as e:  # noqa: BLE001
        log("  (daftar saham dari situs belum tersedia, memakai LQ45:", e, ")")
        url = f"https://raw.githubusercontent.com/{REPO}/{CABANG}/scripts/config.py"
        teks = requests.get(url, timeout=30).text
        kode = re.findall(r'"([A-Z]{4})"', teks.split("SAHAM = [", 1)[1].split("]", 1)[0])
        return kode, kode


def indeks_tersedia() -> dict:
    import requests

    for url in [SITUS + "data/broker/indeks.json",
                f"https://raw.githubusercontent.com/{REPO}/{CABANG}/docs/data/broker/indeks.json"]:
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:  # noqa: BLE001
            pass
    return {}


def berkas_hari_lama(tgl: date) -> dict | None:
    import requests

    url = f"https://raw.githubusercontent.com/{REPO}/{CABANG}/docs/data/broker/hari/{tgl.isoformat()}.json"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return None


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


IPOT_MATI = False  # setelah Indo Premier terbukti tidak bisa diakses, hari berikutnya tidak dicoba lagi


def ambil_hari(tgl: date, kode_list: list[str], terbaru: bool, perlu_broker: bool = True) -> dict:
    """Ambil satu hari bursa. Situs IDX dicoba lebih dulu (satu permintaan) karena sekaligus
    memastikan apakah hari itu libur; Indo Premier (ringkasan broker) dicoba sesudahnya."""
    global IPOT_MATI
    s = tgl.strftime("%m/%d/%Y")
    data = {"tanggal": tgl.isoformat(), "dibuat": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"), "saham": {}}

    idx = ambil_idx(tgl)  # None = gagal; {} = tidak ada perdagangan (libur)
    if idx == {}:
        data["libur"] = True
        return data
    if idx:
        data["idx"] = idx

    ada_transaksi, berhasil, gagal = False, 0, 0
    if perlu_broker and not IPOT_MATI:
        for i, kode in enumerate(kode_list, 1):
            html = ambil(f"{IPOT_BROKER}?code={kode}&start={s}&end={s}&fd=all&board=all")
            if html is None:
                gagal += 1
                if berhasil == 0 and gagal >= 3:
                    IPOT_MATI = True
                    log(f"  Indo Premier tidak bisa diakses ({GAGAL_TERAKHIR}); ringkasan broker dilewati.")
                    break
                continue
            berhasil += 1
            hasil = urai_broker(html)
            if hasil is None:
                continue
            if hasil["b"] or (hasil["tval"] or 0) > 0:
                ada_transaksi = True
                data["saham"][kode] = hasil
            if i % 5 == 0:
                log(f"  {tgl} {i}/{len(kode_list)} saham")
            time.sleep(0.4)
            if berhasil >= 3 and not ada_transaksi and not idx:
                break  # hari libur bursa: tiga saham pun tanpa transaksi
        if terbaru and ada_transaksi:
            html = ambil(IPOT_TOPBROKER)
            if html:
                data["pasar_broker"] = urai_topbroker(html)

    if not idx and not ada_transaksi and (IPOT_MATI or not perlu_broker):
        raise ConnectionError(f"Situs IDX dan Indo Premier sama-sama tidak bisa diakses ({GAGAL_TERAKHIR}).")
    data["libur"] = not idx and not ada_transaksi
    return data


_IDX_SESI = None


IDX_HALAMAN = "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/"
IDX_CACHE: dict[str, dict | None] = {}  # tanggal -> data (diisi lewat browser)
IDX_LEWAT_BROWSER = False
PROFIL_CHROME = Path.home() / ".analisis-saham-chrome"


def ubah_idx(js: dict) -> dict:
    hasil = {}
    for d in js.get("data") or []:
        hasil[d["StockCode"]] = [
            float(d.get("ForeignBuy") or 0), float(d.get("ForeignSell") or 0),
            float(d.get("Close") or 0), float(d.get("Previous") or 0),
            float(d.get("Value") or 0), int(d.get("Frequency") or 0),
            float(d.get("ListedShares") or 0),
        ]
    aktif = sum(1 for v in hasil.values() if v[4] > 0)
    return hasil if aktif else {}


def ambil_idx(tgl: date) -> dict | None:
    """Ringkasan Saham IDX (seluruh saham). None = gagal, {} = tidak ada perdagangan."""
    if IDX_LEWAT_BROWSER:
        return IDX_CACHE.get(tgl.isoformat())
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return None
    global _IDX_SESI
    try:
        if _IDX_SESI is None:
            _IDX_SESI = creq.Session(impersonate="chrome")
            _IDX_SESI.get("https://www.idx.co.id/id", timeout=30)
        r = _IDX_SESI.get(IDX_RINGKASAN.format(tgl.strftime("%Y%m%d")), timeout=40, headers={"Referer": IDX_HALAMAN})
        if r.status_code != 200:
            log(f"  Situs IDX menolak program biasa ({r.status_code}).")
            return None
        hasil = ubah_idx(r.json())
        log(f"  {tgl} situs IDX: {len(hasil)} saham.")
        return hasil
    except Exception as e:  # noqa: BLE001
        log("  Situs IDX tidak bisa diakses:", e)
        return None


def idx_lewat_browser(daftar: list[date], tunggu_detik: int = 240) -> None:
    """Buka Chrome Anda (profil khusus), lewati verifikasi Cloudflare, lalu ambil data
    Ringkasan Saham untuk setiap tanggal dari dalam halaman IDX itu sendiri."""
    global IDX_LEWAT_BROWSER
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        log("  Pustaka 'patchright' belum terpasang; jalankan pasang_windows.bat lagi.")
        return
    IDX_LEWAT_BROWSER = True
    js_ambil = """async (u) => {
        try { const r = await fetch(u, {credentials: 'include', headers: {'Accept': 'application/json'}});
              if (!r.ok) return {status: r.status};
              return {status: 200, data: await r.json()}; }
        catch (e) { return {status: 0, galat: String(e)}; } }"""
    log("Membuka Chrome untuk situs IDX…")
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(PROFIL_CHROME), channel="chrome", headless=False, no_viewport=True,
                args=["--window-size=1000,750"])
        except Exception as e:  # noqa: BLE001
            log("  Chrome tidak bisa dibuka:", e)
            return
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(IDX_HALAMAN, wait_until="domcontentloaded", timeout=90000)
            uji = IDX_RINGKASAN.format(daftar[-1].strftime("%Y%m%d"))
            batas, diberi_tahu = time.time() + tunggu_detik, False
            lolos = False
            while time.time() < batas:
                try:
                    h = page.evaluate(js_ambil, uji)
                except Exception:  # noqa: BLE001
                    h = {"status": 0}  # halaman sedang berpindah (verifikasi selesai)
                if h.get("status") == 200:
                    lolos = True
                    break
                if not diberi_tahu:
                    log(">>> Jika di jendela Chrome muncul kotak verifikasi IDX, klik kotaknya. Menunggu…")
                    diberi_tahu = True
                time.sleep(4)
            if not lolos:
                log("  Verifikasi IDX tidak terlewati dalam waktu tunggu; data IDX dilewati.")
                return
            log("  Verifikasi IDX lolos.")
            for tgl in daftar:
                h = page.evaluate(js_ambil, IDX_RINGKASAN.format(tgl.strftime("%Y%m%d")))
                if h.get("status") == 200:
                    IDX_CACHE[tgl.isoformat()] = ubah_idx(h["data"])
                    log(f"  {tgl} situs IDX: {len(IDX_CACHE[tgl.isoformat()])} saham.")
                else:
                    log(f"  {tgl} situs IDX gagal (status {h.get('status')}).")
                time.sleep(1.0)
        finally:
            ctx.close()


def siapkan_idx(daftar: list[date]) -> None:
    """Coba cara biasa dulu; bila ditolak Cloudflare, pakai jendela Chrome."""
    if not daftar:
        return
    if ambil_idx(daftar[-1]) is None:
        idx_lewat_browser(daftar)


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
    if "--cek" in sys.argv:
        t = hari_bursa_terakhir(1)[0].strftime("%m/%d/%Y")
        log(f"Menguji koneksi ke Indo Premier (BBCA, {t})…")
        html = ambil(f"{IPOT_BROKER}?code=BBCA&start={t}&end={t}&fd=all&board=all")
        if html is None:
            log("GAGAL terhubung ke Indo Premier.")
        else:
            h = urai_broker(html)
            log(f"BERHASIL: {len(h['b'])} pembeli, {len(h['s'])} penjual, nilai {h['tval']}, asing bersih {h['fnet']}")
        log("Menguji koneksi ke situs IDX…")
        siapkan_idx(hari_bursa_terakhir(1))
        hasil = ambil_idx(hari_bursa_terakhir(1)[0])
        log("GAGAL terhubung ke IDX." if hasil is None else ("IDX: tidak ada perdagangan pada tanggal itu." if not hasil else "BERHASIL terhubung ke IDX."))
        return
    log("Mulai mengumpulkan data…")
    kode_ramai, kode_lq45 = daftar_saham()
    kode_list = kode_ramai
    ind = indeks_tersedia()
    libur, ada_broker, ada_idx = set(ind.get("libur", [])), set(ind.get("broker", [])), set(ind.get("idx", []))
    if "broker" not in ind:  # indeks versi lama: anggap hari yang tercatat sudah punya broker
        ada_broker = set(ind.get("tanggal", []))
    semua_hari = [d for d in hari_bursa_terakhir(HARI_MUNDUR) if d.isoformat() not in libur]
    perlu_idx = [d for d in semua_hari if d.isoformat() not in ada_idx]
    perlu_broker = [d for d in semua_hari if d.isoformat() not in ada_broker]

    global IPOT_MATI
    if perlu_broker:
        t = perlu_broker[-1].strftime("%m/%d/%Y")
        if ambil(f"{IPOT_BROKER}?code=BBCA&start={t}&end={t}&fd=all&board=all", coba=2) is None:
            IPOT_MATI = True
            log(f"Indo Premier belum bisa diakses ({GAGAL_TERAKHIR}); ringkasan broker dicoba lagi nanti.")
            perlu_broker = []
    hari = sorted(set(perlu_idx) | set(perlu_broker))
    if not hari:
        log("Data IDX sudah lengkap; ringkasan broker menunggu Indo Premier pulih. Selesai." if IPOT_MATI
            else "Semua data hari bursa terakhir sudah lengkap. Selesai.")
        return
    baru = set(hari_bursa_terakhir(HARI_BROKER_PENUH))
    log(f"{len(kode_ramai)} saham ramai ({len(kode_lq45)} LQ45). Perlu data IDX: {len(perlu_idx)} hari; perlu ringkasan broker: {len(perlu_broker)} hari.")
    siapkan_idx(perlu_idx)
    berkas = {}
    for tgl in hari:
        lama = berkas_hari_lama(tgl) if tgl.isoformat() in (ada_idx | ada_broker) else None
        try:
            d = ambil_hari(tgl, kode_ramai if tgl in baru else kode_lq45, terbaru=(tgl == hari[-1]),
                           perlu_broker=tgl in perlu_broker)
        except ConnectionError as e:
            if lama is None:
                log(f"{tgl}: dilewati ({e})")
                continue
            d = {"tanggal": tgl.isoformat(), "saham": {}, "libur": False}
        if lama:  # pertahankan bagian lama yang tidak diambil ulang
            if not d.get("saham") and lama.get("saham"):
                d["saham"] = lama["saham"]
                if lama.get("pasar_broker") and not d.get("pasar_broker"):
                    d["pasar_broker"] = lama["pasar_broker"]
            if not d.get("idx") and lama.get("idx"):
                d["idx"] = lama["idx"]
            d["libur"] = d["libur"] and not d.get("idx") and not d.get("saham")
        log(f"{tgl}: {'libur bursa' if d['libur'] else str(len(d['saham'])) + ' saham broker, ' + ('ada' if d.get('idx') else 'tanpa') + ' data IDX'}")
        berkas[f"docs/data/broker/hari/{tgl.isoformat()}.json"] = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    if not berkas:
        log("Tidak ada data yang bisa diunggah.")
        return
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
