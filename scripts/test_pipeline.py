# -*- coding: utf-8 -*-
"""Pipeline regresyon/doğrulama testi: fihrist çek -> capture -> eşleştir -> rapor.

Kullanım:
  python scripts/test_pipeline.py                 # son 7 gün
  python scripts/test_pipeline.py --days 14
  python scripts/test_pipeline.py --start 2026-06-16 --end 2026-06-22
  python scripts/test_pipeline.py --db rg_data.db --root .

Feed/GitHub push YAPMAZ — yalnızca çekim + eşleştirme doğrulaması.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from rg import matcher, scraper
from rg.db import Database, default_seed_paths


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="RG pipeline doğrulama testi")
    p.add_argument("--start", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--end", type=dt.date.fromisoformat, help="YYYY-MM-DD (varsayılan bugün)")
    p.add_argument("--days", type=int, default=7, help="--start yoksa son N gün (vars. 7)")
    p.add_argument("--db", default="rg_data.db")
    p.add_argument("--root", default=".", help="clean CSV kök dizini")
    p.add_argument("--fresh", action="store_true", help="DB'yi sıfırla")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    end = a.end or dt.date.today()
    start = a.start or (end - dt.timedelta(days=a.days - 1))

    if a.fresh and os.path.exists(a.db):
        os.remove(a.db)
    db = Database(a.db)
    counts = db.load_seed(**default_seed_paths(a.root))
    catalog = db.catalog_for_matching()
    mt = matcher.Matcher(catalog)

    print("=" * 72)
    print(f"SEED: {counts}  |  katalog (rg_yayinlanir=True): {len(catalog)}")
    print(f"ARALIK: {start} .. {end}")
    print("=" * 72)

    total = deg = auto_n = near_n = 0
    fihrist_total = probe_total = 0
    probe_missed_all = []
    auto_rows, near_rows, sayilar = [], [], []

    for cap in scraper.capture_range(start, end):
        db.store_capture(cap)
        mk = f" (Mükerrer {cap.mukerrer})" if cap.mukerrer else ""
        st = cap.verify_stats or {}
        nf, npm = st.get("fihrist", 0), st.get("probe_missed", 0)
        fihrist_total += nf
        probe_total += npm
        tag = f"  ⚠ PROBE+{npm} (no: {st.get('missed_nos')})" if npm else ""
        if npm:
            for n in st.get("missed_nos", []):
                it = next((x for x in cap.items if x.doc_no == n and x.source == "probe"), None)
                if it:
                    probe_missed_all.append((cap, it))
        sayilar.append(f"{cap.rg_tarihi} / sayı {cap.rg_sayi}{mk}: "
                       f"{len(cap.items)} madde (fihrist={nf}, probe+={npm}){tag}")
        for it in cap.items:
            total += 1
            in_scope = it.section in scraper.MEVZUAT_SECTIONS
            res = mt.match(it.baslik)
            if res.is_degisiklik:
                deg += 1
            # AUTO -> changes
            db.record_change(
                guid=it.url, rg_tarihi=it.rg_tarihi, rg_sayi=it.rg_sayi,
                mukerrer=it.mukerrer, section=it.section, baslik=it.baslik, url=it.url,
                is_degisiklik=res.is_degisiklik,
                matched_mevzuat_id=res.matched_mevzuat_id if in_scope else None,
                score=res.score, target_extracted=res.target,
            )
            if in_scope and res.band == "auto":
                auto_n += 1
                auto_rows.append((res, it))
            # near-miss -> AYRI tablo (changes'e GİRMEZ)
            elif in_scope and res.band == "near_miss":
                near_n += 1
                db.record_near_miss(
                    guid=it.url, rg_tarihi=it.rg_tarihi, rg_sayi=it.rg_sayi,
                    mukerrer=it.mukerrer, section=it.section, baslik=it.baslik,
                    url=it.url, candidate_mevzuat_id=res.best_id, score=res.score,
                    target_extracted=res.target,
                )
                near_rows.append((res, it))

    print("\n--- ÇEKİLEN SAYILAR ---")
    for s in sayilar:
        print("  ", s)

    print("\n--- TAMLIK DOĞRULAMA (fihrist parse vs probe) ---")
    print(f"  Fihristten parse edilen doküman : {fihrist_total}")
    print(f"  Probe ile yakalanan KAÇAN       : {probe_total}")
    if probe_total == 0:
        print("  ✓ Fihrist parse sayısı = gerçek doküman sayısı (kaçan yok)")
    else:
        print("  ⚠ Fihriste düşmemiş ama gerçekte var olan dokümanlar:")
        for cap, it in probe_missed_all:
            print(f"     {it.url}")
            print(f"       başlık(dokümandan)={it.baslik[:80]}")

    print("\n--- ÖZET ---")
    print(f"  Toplam madde (fihrist+probe)      : {total}")
    print(f"  'Değişiklik' tipi                 : {deg}")
    print(f"  AUTO eşleşen (skor>=90, changes)  : {auto_n}")
    print(f"  NEAR-MISS (80<=skor<90, ayrı log) : {near_n}")

    print("\n--- AUTO EŞLEŞENLER (changes) ---")
    if not auto_rows:
        print("  (yok)")
    for res, it in sorted(auto_rows, key=lambda x: -x[0].score):
        print(f"  [{res.matched_mevzuat_id}] {res.score}  {it.rg_tarihi}  {it.baslik[:70]}")

    print("\n--- NEAR-MISS (sadece görünürlük; otomatik güncelleme YOK) ---")
    if not near_rows:
        print("  (yok)")
    for res, it in sorted(near_rows, key=lambda x: -x[0].score):
        print(f"  ~[{res.best_id}] {res.score}  {it.rg_tarihi}  {it.baslik[:70]}")
        print(f"     top3={res.top3}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
