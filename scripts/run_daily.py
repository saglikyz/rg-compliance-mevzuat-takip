# -*- coding: utf-8 -*-
"""Günlük üretim akışı: RG çek -> eşleştir -> feed üret -> (opsiyonel) GitHub'a push.

Akış:
  1) capture_range(son N gün, verify=True) -> store_capture
  2) matcher: AUTO (skor>=90) -> change tablosu; near-miss [80,90) -> near_miss tablosu
  3) feed.write_feed(docs/feed.xml, kayan pencere = FEED_WINDOW_DAYS)
  4) push_feed() — YALNIZCA --push verilirse (varsayılan: dry-run, push YOK)

Her adım logs/run_daily_YYYYMMDD.log dosyasına + konsola loglanır.
Bir adım hata verirse akış DURUR ve hata loglanır (exit kodu != 0).

Kullanım:
  python scripts/run_daily.py                 # son 7 gün, DRY-RUN (push yok)
  python scripts/run_daily.py --days 14
  python scripts/run_daily.py --push          # push'u AÇ (GITHUB_TOKEN gerekir)
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Kurumsal SSL inspection (kök CA) ortamında requests/PyGithub'ın certifi yerine
# Windows sertifika deposunu kullanması için (git schannel gibi). Yoksa sessiz geç.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:  # dotenv yoksa ortam değişkenleri elle verilmiş olabilir
    pass

import config
from rg import feed, matcher, scraper
from rg.db import Database, default_seed_paths

log = logging.getLogger("rg.run_daily")


def _setup_logging() -> str:
    log_dir = os.path.join(ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"run_daily_{dt.date.today():%Y%m%d}.log")
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO, format=fmt,
        handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    return log_path


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="RG günlük üretim akışı")
    p.add_argument("--start", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--end", type=dt.date.fromisoformat, help="YYYY-MM-DD (vars. bugün)")
    p.add_argument("--days", type=int, default=7, help="--start yoksa son N gün (vars. 7)")
    p.add_argument("--db", default=config.DB_PATH)
    p.add_argument("--root", default=ROOT, help="clean CSV kök dizini")
    p.add_argument("--push", action="store_true",
                   help="feed'i GitHub'a push et (varsayılan: dry-run, push YOK)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    log_path = _setup_logging()
    end = a.end or dt.date.today()
    start = a.start or (end - dt.timedelta(days=a.days - 1))
    mode = "PUSH" if a.push else "DRY-RUN (push YOK)"
    log.info("=== run_daily başladı | mod=%s | aralık=%s..%s | log=%s ===",
             mode, start, end, log_path)

    db = None
    try:
        # --- seed + katalog ---
        db = Database(a.db)
        counts = db.load_seed(**default_seed_paths(a.root))
        catalog = db.catalog_for_matching()
        mt = matcher.Matcher(catalog)
        log.info("seed=%s | katalog(rg_yayinlanir=1)=%d", counts, len(catalog))

        # --- 1) çekim + 2) eşleştirme ---
        n_sayi = n_madde = n_auto = n_near = n_probe = 0
        for cap in scraper.capture_range(start, end, verify=True):
            db.store_capture(cap)
            n_sayi += 1
            st = cap.verify_stats or {}
            n_probe += st.get("probe_missed", 0)
            log.info("sayı %s/%s (mük=%d): %d madde (fihrist=%d, probe+=%d)",
                     cap.rg_tarihi, cap.rg_sayi, cap.mukerrer, len(cap.items),
                     st.get("fihrist", 0), st.get("probe_missed", 0))
            for it in cap.items:
                n_madde += 1
                in_scope = it.section in scraper.MEVZUAT_SECTIONS
                res = mt.match(it.baslik)
                # AUTO -> change tablosu (yalnızca kapsam içi eşleşme matched_id taşır)
                db.record_change(
                    guid=it.url, rg_tarihi=it.rg_tarihi, rg_sayi=it.rg_sayi,
                    mukerrer=it.mukerrer, section=it.section, baslik=it.baslik,
                    url=it.url, is_degisiklik=res.is_degisiklik,
                    matched_mevzuat_id=res.matched_mevzuat_id if in_scope else None,
                    score=res.score, target_extracted=res.target,
                )
                if in_scope and res.band == "auto":
                    n_auto += 1
                    log.info("AUTO [%s] %.1f %s", res.matched_mevzuat_id,
                             res.score, it.baslik[:70])
                elif in_scope and res.band == "near_miss":
                    n_near += 1
                    db.record_near_miss(
                        guid=it.url, rg_tarihi=it.rg_tarihi, rg_sayi=it.rg_sayi,
                        mukerrer=it.mukerrer, section=it.section, baslik=it.baslik,
                        url=it.url, candidate_mevzuat_id=res.best_id,
                        score=res.score, target_extracted=res.target,
                    )
        log.info("çekim+eşleştirme bitti: %d sayı, %d madde, %d AUTO, %d near-miss, %d probe+",
                 n_sayi, n_madde, n_auto, n_near, n_probe)

        # --- 3) feed üret (kayan pencere) ---
        window = config.FEED_WINDOW_DAYS
        rows = db.changes_window(window)
        items = feed.items_from_changes(rows)
        out_path = feed.write_feed(config.FEED_OUT, items, self_url=config.FEED_SELF_URL)
        log.info("feed yazıldı: %s (%d item, kayan pencere %d gün)",
                 out_path, len(items), window)

        # --- 4) push (opsiyonel) ---
        if a.push:
            from push_feed import push_feed
            log.info("push başlıyor -> %s", os.environ.get("GITHUB_REPO"))
            sha = push_feed(local_path=config.FEED_OUT)
            log.info("push OK: commit %s", sha)
        else:
            log.info("DRY-RUN: push atlandı (--push verilmedi). Feed yalnızca lokalde: %s",
                     out_path)

        log.info("=== run_daily bitti OK | feed item=%d | mod=%s ===", len(items), mode)
        # özet stdout (insan okuması için)
        print("\n--- ÖZET ---")
        print(f"  aralık            : {start} .. {end}")
        print(f"  çekilen sayı      : {n_sayi}")
        print(f"  toplam madde      : {n_madde}")
        print(f"  AUTO (changes)    : {n_auto}")
        print(f"  near-miss (ayrı)  : {n_near}")
        print(f"  probe+ (kaçan)    : {n_probe}")
        print(f"  FEED item (30 gün): {len(items)}")
        print(f"  feed dosyası      : {out_path}")
        print(f"  push              : {'YAPILDI' if a.push else 'YOK (dry-run)'}")
        return 0

    except Exception:
        log.exception("run_daily HATA — akış durduruldu")
        return 1
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
