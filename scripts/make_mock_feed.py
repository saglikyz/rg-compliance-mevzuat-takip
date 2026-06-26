# -*- coding: utf-8 -*-
"""Power Automate flow testi için MOCK feed üretir -> docs/feed-mock.xml.

Gerçek üretim feed'iyle (docs/feed.xml) BİREBİR aynı yapı: rg/feed.py'nin
build_feed/FeedItem kodu yeniden kullanılır. Tek fark MOCK damgaları:
  - guid başına "MOCK-" öneki
  - title başına "[TEST] "
  - rgUrl gerçek RG formatında ama açıkça sahte doküman no (9001+)

GERÇEK PIPELINE'A DOKUNMAZ:
  - rg_data.db SADECE READ-ONLY açılır (mevzuat adlarını okumak için); hiçbir
    tabloya (change/near_miss/capture) yazmaz -> demo kirliliği OLMAZ.
  - docs/feed.xml'e DOKUNMAZ; yalnızca docs/feed-mock.xml yazar.

Kullanım:
  python scripts/make_mock_feed.py
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import config
from rg.feed import FeedItem, build_feed

MOCK_OUT = os.path.join(ROOT, "docs", "feed-mock.xml")
MOCK_SELF_URL = "https://saglikyz.github.io/rg-compliance-mevzuat-takip/feed-mock.xml"

# Gerçek katalogdan MEV-ID'ler (PA eşlemesi gerçekçi olsun) + sahte RG referansı.
MOCK_SPECS = [
    # (mevzuat_id, rg_tarihi, rg_sayi, sahte_doc_no)
    ("MEV-006", "2026-06-24", "33290", 9001),
    ("MEV-030", "2026-06-25", "33291", 9002),
    ("MEV-048", "2026-06-26", "33292", 9003),
]


class MockFeedItem(FeedItem):
    """FeedItem ile aynı; guid'e 'MOCK-' öneki ekler. id alanı GERÇEK kalır."""

    @property
    def guid(self) -> str:
        return "MOCK-" + super().guid


def _real_names(ids: list[str]) -> dict[str, str]:
    """mevzuat adlarını rg_data.db'den READ-ONLY oku (yazma imkânsız)."""
    uri = f"file:{config.DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        q = "SELECT mevzuat_id, ad FROM mevzuat WHERE mevzuat_id IN (%s)" % (
            ",".join("?" * len(ids)))
        return {r[0]: r[1] for r in con.execute(q, ids).fetchall()}
    finally:
        con.close()


def build_mock_items() -> list[MockFeedItem]:
    names = _real_names([s[0] for s in MOCK_SPECS])
    items: list[MockFeedItem] = []
    for mid, tarih, sayi, doc_no in MOCK_SPECS:
        ad = names.get(mid, mid)
        y, m = tarih[:4], tarih[5:7]
        rg_url = f"https://www.resmigazete.gov.tr/eskiler/{y}/{m}/{y}{m}{tarih[8:10]}-{doc_no}.htm"
        items.append(MockFeedItem(
            mevzuat_id=mid,                 # GERÇEK id -> description.fields/id
            mevzuat_ad=f"[TEST] {ad}",      # title MOCK damgalı
            rg_tarihi=tarih, rg_sayi=sayi, rg_url=rg_url, mukerrer=0,
        ))
    return items


def main() -> int:
    items = build_mock_items()
    xml = build_feed(items, self_url=MOCK_SELF_URL)
    os.makedirs(os.path.dirname(MOCK_OUT), exist_ok=True)
    with open(MOCK_OUT, "w", encoding="utf-8") as fh:
        fh.write(xml)
    print(f"mock feed yazıldı: {MOCK_OUT} ({len(items)} item)")
    for it in items:
        print(f"  guid={it.guid}  title={it.mevzuat_ad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
