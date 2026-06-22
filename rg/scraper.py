# -*- coding: utf-8 -*-
"""Resmî Gazete günlük fihrist scraper.

Kaynak: https://www.resmigazete.gov.tr/eskiler/YYYY/MM/YYYYMMDD.htm
(WAF'lı /Home/Filter POST'a gerek yok; günlük fihrist düz GET ile gelir.)
Encoding: windows-1254.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("rg.scraper")

BASE = "https://www.resmigazete.gov.tr"
ENCODING = "windows-1254"

_TR_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

# Fihristte beklenen bölüm etiketleri (en yakın önceki etiket = dokümanın bölümü)
_SECTION_LABELS = [
    "YASAMA BÖLÜMÜ", "YÜRÜTME VE İDARE BÖLÜMÜ", "YARGI BÖLÜMÜ", "İLÂN BÖLÜMÜ",
    "KANUNLAR", "CUMHURBAŞKANI KARARLARI", "CUMHURBAŞKANLIĞI KARARNAMELERİ",
    "YÖNETMELİKLER", "YÖNETMELİK", "TEBLİĞLER", "TEBLİĞ", "GENELGE", "KARARLAR",
    "ANAYASA MAHKEMESİ KARARLARI", "YARGITAY KARARLARI", "DANIŞTAY KARARLARI",
]
# RG'de "mevzuat" sayılan (eşleştirmeye değer) bölümler
MEVZUAT_SECTIONS = {
    "KANUNLAR", "YÖNETMELİKLER", "YÖNETMELİK", "TEBLİĞLER", "TEBLİĞ",
    "CUMHURBAŞKANI KARARLARI", "CUMHURBAŞKANLIĞI KARARNAMELERİ",
}


@dataclass
class GazetteItem:
    """Fihristteki tek bir doküman satırı."""
    rg_tarihi: str          # 'YYYY-MM-DD'
    rg_sayi: str            # '33286'
    mukerrer: int           # 0 = asıl, 1.. = mükerrer
    section: str            # 'YÖNETMELİK' vb.
    sira: str               # '7584' veya '––'
    baslik: str
    url: str                # tam URL (guid olarak da kullanılır)
    doc_no: int = 0         # {basename}-{N}.htm içindeki N
    source: str = "fihrist" # 'fihrist' | 'probe' (probe = fihriste düşmemiş, emniyetle yakalandı)


@dataclass
class GazetteCapture:
    """Bir Resmî Gazete sayısının (asıl ya da mükerrer) fihristi."""
    rg_tarihi: str
    rg_sayi: str
    mukerrer: int
    basename: str
    url: str
    items: list[GazetteItem] = field(default_factory=list)
    verify_stats: dict | None = None   # _verify_completeness çıktısı


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (rg-compliance-mevzuat-takip)"})
    retry = Retry(
        total=4, connect=4, read=4, backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _parse_header(html: str) -> tuple[str | None, str | None, bool]:
    """Fihrist başlığından (rg_tarihi 'YYYY-MM-DD', rg_sayi, mukerrer?) ayıkla."""
    head = _strip_tags(html[:3000])
    sayi = None
    m = re.search(r"Tarihli\s+ve\s+(\d+)\s+Sayılı", head, re.I)
    if m:
        sayi = m.group(1)
    tarih = None
    m = re.search(r"(\d{1,2})\s+([A-Za-zçğıöşüÇĞİÖŞÜ]+)\s+(\d{4})\s+Tarihli", head)
    if m:
        gun, ay_adi, yil = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        ay = _TR_MONTHS.get(ay_adi)
        if ay:
            try:
                tarih = dt.date(yil, ay, gun).isoformat()
            except ValueError:
                tarih = None
    mukerrer = bool(re.search(r"Mükerrer", head, re.I))
    return tarih, sayi, mukerrer


def _parse_items(html: str, basename: str, cap: GazetteCapture) -> None:
    """Fihristteki doküman anchor'larını bölümleriyle birlikte çıkar."""
    # Bölüm etiketlerinin konumları
    label_pos: list[tuple[int, str]] = []
    for lab in _SECTION_LABELS:
        for m in re.finditer(re.escape(lab), html):
            label_pos.append((m.start(), lab))
    label_pos.sort()

    def section_at(pos: int) -> str:
        cur = ""
        for p, lab in label_pos:
            if p <= pos:
                cur = lab
            else:
                break
        return cur

    # {basename}-{n}.(htm|pdf) biçimli doküman linkleri (İlan main.aspx linkleri hariç)
    anchor_re = re.compile(
        r'<a[^>]+href="(' + re.escape(basename) + r'-(\d+)\.(?:htm|pdf))"[^>]*>(.*?)</a>',
        re.S | re.I,
    )
    for m in anchor_re.finditer(html):
        href, num, inner = m.group(1), int(m.group(2)), m.group(3)
        text = _strip_tags(inner).replace("\xa0", " ").strip()
        # baştaki sıra no / '––'
        sm = re.match(r"^\s*(\d+|[–-]{2,})\s*&?nbsp;?\s*(.*)$", text)
        if sm:
            sira, baslik = sm.group(1), sm.group(2).strip()
        else:
            sira, baslik = "", text
        baslik = baslik.replace("&nbsp;", " ").strip()
        if not baslik:
            continue
        cap.items.append(GazetteItem(
            rg_tarihi=cap.rg_tarihi, rg_sayi=cap.rg_sayi, mukerrer=cap.mukerrer,
            section=section_at(m.start()), sira=sira, baslik=baslik,
            url=f"{BASE}/eskiler/{basename[:4]}/{basename[4:6]}/{href}",
            doc_no=num, source="fihrist",
        ))

    # İlan / main.aspx linkleri — kapsam dışı (mevzuat değil) ama görünürlük için logla
    ilan = re.findall(r'href="([^"]*(?:main\.aspx|/ilanlar/)[^"]*)"', html, re.I)
    if ilan:
        log.info("İlan/kapsam-dışı link atlandı (%d): %s ...", len(ilan), ilan[0][:80])


def _doc_url(basename: str, num: int, ext: str) -> str:
    return f"{BASE}/eskiler/{basename[:4]}/{basename[4:6]}/{basename}-{num}.{ext}"


def _title_from_html(html: str) -> str:
    """Probe ile bulunan dokümanın kendi sayfasından kaba başlık çıkar."""
    body = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<script[^>]*>.*?</script>", " ", body, flags=re.S | re.I)
    text = _strip_tags(body)
    text = re.sub(r"^(Print|Clean|false|true|\d|TR|X-NONE|MicrosoftInternetExplorer\d|\s)+", "", text)
    return text[:160].strip()


def _probe_doc(sess: requests.Session, basename: str, num: int) -> tuple[str, str, str] | None:
    """{basename}-{num} dokümanı gerçekte var mı? (.htm sonra .pdf). (ext, url, title) ya da None."""
    for ext in ("htm", "pdf"):
        url = _doc_url(basename, num, ext)
        try:
            r = sess.get(url, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code == 200 and r.content:
            title = ""
            if ext == "htm":
                title = _title_from_html(r.content.decode(ENCODING, "replace"))
            return ext, url, title
    return None


def _verify_completeness(sess: requests.Session, cap: GazetteCapture,
                         *, gap_tolerance: int = 3, forward_cap: int = 60) -> dict:
    """Fihrist parse'ını probe ile doğrula; kaçan dokümanları yakala + WARNING logla.

    - 1..N arası fihriste DÜŞMEYEN ama gerçekte VAR olanları bul (backfill).
    - N+1, N+2 ... ileriye probe; ardışık `gap_tolerance` boşta dur.
    """
    found = {it.doc_no for it in cap.items if it.doc_no}
    maxn = max(found) if found else 0
    missed: list[int] = []

    def _capture_probe(num: int, hit: tuple[str, str, str]) -> None:
        ext, url, title = hit
        missed.append(num)
        log.warning("fihrist parse eksik: %s (başlık dokümandan: %.60s)", url, title or "?")
        cap.items.append(GazetteItem(
            rg_tarihi=cap.rg_tarihi, rg_sayi=cap.rg_sayi, mukerrer=cap.mukerrer,
            section="(PROBE)", sira="", baslik=title or f"[{cap.basename}-{num}.{ext}]",
            url=url, doc_no=num, source="probe",
        ))

    # 1..N arası boşluklar
    for num in range(1, maxn + 1):
        if num in found:
            continue
        hit = _probe_doc(sess, cap.basename, num)
        if hit:
            _capture_probe(num, hit)

    # N+1 ileriye, ardışık gap_tolerance boşa kadar
    consecutive_empty = 0
    num = maxn + 1
    while consecutive_empty < gap_tolerance and num <= maxn + forward_cap:
        hit = _probe_doc(sess, cap.basename, num)
        if hit:
            _capture_probe(num, hit)
            consecutive_empty = 0
        else:
            consecutive_empty += 1
        num += 1

    cap.items.sort(key=lambda it: it.doc_no)
    return {"fihrist": len(found), "probe_missed": len(missed),
            "missed_nos": sorted(missed), "max_no": maxn}


def _fetch_one(sess: requests.Session, day: dt.date, mukerrer: int,
               *, verify: bool = True) -> GazetteCapture | None:
    """Tek bir fihrist sayfasını çek (asıl mukerrer=0, mükerrer>=1)."""
    basename = day.strftime("%Y%m%d") + (f"M{mukerrer}" if mukerrer else "")
    url = f"{BASE}/eskiler/{day:%Y}/{day:%m}/{basename}.htm"
    try:
        r = sess.get(url, timeout=30)
    except requests.RequestException as e:
        log.warning("fetch hata %s: %s", url, e)
        return None
    if r.status_code == 404:
        return None  # o gün / o mükerrer yok
    if r.status_code != 200 or not r.content:
        log.warning("beklenmeyen durum %s -> %s", url, r.status_code)
        return None
    html = r.content.decode(ENCODING, "replace")
    if "Resmî Gazete" not in html[:3000]:
        return None  # fihrist değil
    tarih, sayi, mk = _parse_header(html)
    cap = GazetteCapture(
        rg_tarihi=tarih or day.isoformat(), rg_sayi=sayi or "",
        mukerrer=mukerrer, basename=basename, url=url,
    )
    _parse_items(html, basename, cap)
    if verify:
        cap.verify_stats = _verify_completeness(sess, cap)
    return cap


def fetch_day(day: dt.date, *, sess: requests.Session | None = None,
              max_mukerrer: int = 9, verify: bool = True) -> list[GazetteCapture]:
    """Bir günün tüm sayılarını (asıl + mükerrer) döndür. Yayım yoksa boş liste."""
    sess = sess or _session()
    out: list[GazetteCapture] = []
    asil = _fetch_one(sess, day, 0, verify=verify)
    if asil is None:
        log.info("yayım yok / erişilemedi: %s", day.isoformat())
        return out
    out.append(asil)
    for k in range(1, max_mukerrer + 1):
        mk = _fetch_one(sess, day, k, verify=verify)
        if mk is None:
            break  # ardışık mükerrer biter
        out.append(mk)
    return out


def capture_range(start: dt.date, end: dt.date, *,
                  sess: requests.Session | None = None,
                  verify: bool = True) -> Iterator[GazetteCapture]:
    """[start, end] (dahil) tarih aralığındaki tüm RG sayılarını üret."""
    sess = sess or _session()
    day = start
    while day <= end:
        for cap in fetch_day(day, sess=sess, verify=verify):
            yield cap
        day += dt.timedelta(days=1)
