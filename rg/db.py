# -*- coding: utf-8 -*-
"""SQLite kalıcılık katmanı — 4 katmanlı mevzuat modeli + capture/change.

Katmanlar: mevzuat -> bolum -> madde -> fikra (fikra tanımlı ama şu an boş).
"""
from __future__ import annotations

import csv
import logging
import os
import sqlite3
from typing import Iterable

log = logging.getLogger("rg.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mevzuat (
    mevzuat_id     TEXT PRIMARY KEY,
    ad             TEXT NOT NULL,
    kategori       TEXT,
    belge_turu     TEXT,
    kaynak         TEXT,
    rg_tarihi      TEXT,
    rg_sayi        TEXT,
    rg_yayinlanir  INTEGER NOT NULL DEFAULT 0,
    is_updated     TEXT,
    update_date    TEXT
);
CREATE TABLE IF NOT EXISTS bolum (
    bolum_id          TEXT PRIMARY KEY,
    mevzuat_id        TEXT NOT NULL REFERENCES mevzuat(mevzuat_id),
    bolum_no          TEXT,
    bolum_aciklamasi  TEXT,
    is_updated        TEXT
);
CREATE TABLE IF NOT EXISTS madde (
    madde_id       TEXT PRIMARY KEY,
    bolum_id       TEXT NOT NULL REFERENCES bolum(bolum_id),
    mevzuat_id     TEXT NOT NULL REFERENCES mevzuat(mevzuat_id),
    bolum_no       TEXT,
    madde_no       TEXT,
    madde_turu     TEXT,
    madde_basligi  TEXT,
    is_updated     TEXT
);
CREATE TABLE IF NOT EXISTS fikra (
    fikra_id          TEXT PRIMARY KEY,
    madde_id          TEXT NOT NULL REFERENCES madde(madde_id),
    madde_no          TEXT,
    fikra_no          INTEGER,
    fikra_turu        TEXT,
    fikra_icerik      TEXT,
    fikra_metni_html  TEXT,
    is_updated        TEXT,
    update_date       TEXT
);
CREATE TABLE IF NOT EXISTS capture (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rg_tarihi   TEXT,
    rg_sayi     TEXT,
    mukerrer    INTEGER,
    basename    TEXT,
    url         TEXT,
    fetched_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(basename)
);
CREATE TABLE IF NOT EXISTS capture_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id  INTEGER REFERENCES capture(id),
    section     TEXT,
    sira        TEXT,
    baslik      TEXT,
    url         TEXT
);
CREATE TABLE IF NOT EXISTS change (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    guid                TEXT UNIQUE NOT NULL,
    rg_tarihi           TEXT,
    rg_sayi             TEXT,
    mukerrer            INTEGER,
    section             TEXT,
    baslik              TEXT,
    url                 TEXT,
    is_degisiklik       INTEGER,
    matched_mevzuat_id  TEXT,
    score               REAL,
    target_extracted    TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
-- near-miss: [80,90) bandı; OTOMATİK GÜNCELLEME DEĞİL, sadece insan görünürlüğü.
-- changes'ten ayrı durur, feed'e GİRMEZ.
CREATE TABLE IF NOT EXISTS near_miss (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    guid                TEXT UNIQUE NOT NULL,
    rg_tarihi           TEXT,
    rg_sayi             TEXT,
    mukerrer            INTEGER,
    section             TEXT,
    baslik              TEXT,
    url                 TEXT,
    candidate_mevzuat_id TEXT,
    score               REAL,
    target_extracted    TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_madde_mevzuat ON madde(mevzuat_id);
CREATE INDEX IF NOT EXISTS ix_bolum_mevzuat ON bolum(mevzuat_id);
CREATE INDEX IF NOT EXISTS ix_change_tarih ON change(rg_tarihi);
"""


def _truthy(v: str) -> int:
    return 1 if str(v).strip().lower() in ("true", "1", "evet", "yes") else 0


class Database:
    def __init__(self, path: str = "rg_data.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- seed yükleme ----------
    def _read_csv(self, path: str) -> list[dict]:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    def load_seed(self, *, mevzuat_csv: str, bolum_csv: str, madde_csv: str,
                  replace: bool = True) -> dict[str, int]:
        """Clean CSV'leri mevzuat/bolum/madde tablolarına yükle (fikra boş kalır)."""
        c = self.conn
        if replace:
            for t in ("fikra", "madde", "bolum", "mevzuat"):
                c.execute(f"DELETE FROM {t}")
        mev = self._read_csv(mevzuat_csv)
        c.executemany(
            "INSERT INTO mevzuat (mevzuat_id, ad, kategori, belge_turu, kaynak, "
            "rg_tarihi, rg_sayi, rg_yayinlanir, is_updated, update_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r["MevzuatID"], r["MevzuatAdı"], r.get("Kategori"), r.get("BelgeTürü"),
              r.get("Kaynak"), r.get("RGTarihi") or None, r.get("RGSayi") or None,
              _truthy(r.get("rg_yayinlanir", "")), r.get("isUpdated"),
              r.get("updateDate")) for r in mev],
        )
        bol = self._read_csv(bolum_csv)
        c.executemany(
            "INSERT INTO bolum (bolum_id, mevzuat_id, bolum_no, bolum_aciklamasi, is_updated) "
            "VALUES (?,?,?,?,?)",
            [(r["BolumID"], r["BolumID"].rsplit("-B", 1)[0], r.get("BölümNo"),
              r.get("BölümAçıklaması"), r.get("isUpdated")) for r in bol],
        )
        mad = self._read_csv(madde_csv)
        c.executemany(
            "INSERT INTO madde (madde_id, bolum_id, mevzuat_id, bolum_no, madde_no, "
            "madde_turu, madde_basligi, is_updated) VALUES (?,?,?,?,?,?,?,?)",
            [(r["MaddeID"], r["BolumID"], r["MaddeID"].rsplit("-B", 1)[0].split("-M")[0]
              if "-B" in r["MaddeID"] else r["BolumID"].rsplit("-B", 1)[0],
              r.get("BölümNo"), r.get("MaddeNo"), r.get("MaddeTürü"),
              r.get("MaddeBaşlığı"), r.get("isUpdated")) for r in mad],
        )
        c.commit()
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("mevzuat", "bolum", "madde", "fikra")}
        log.info("seed yüklendi: %s", counts)
        return counts

    # ---------- eşleştirme kataloğu ----------
    def catalog_for_matching(self) -> list[tuple[str, str]]:
        """Sadece rg_yayinlanir=True olan mevzuatlar (RG taramasına giren 42)."""
        cur = self.conn.execute(
            "SELECT mevzuat_id, ad FROM mevzuat WHERE rg_yayinlanir = 1 ORDER BY mevzuat_id"
        )
        return [(r["mevzuat_id"], r["ad"]) for r in cur.fetchall()]

    # ---------- capture ----------
    def store_capture(self, cap) -> int:
        """Bir GazetteCapture'ı (sayı + fihrist satırları) kaydet. capture.id döner."""
        c = self.conn
        cur = c.execute(
            "INSERT OR IGNORE INTO capture (rg_tarihi, rg_sayi, mukerrer, basename, url) "
            "VALUES (?,?,?,?,?)",
            (cap.rg_tarihi, cap.rg_sayi, cap.mukerrer, cap.basename, cap.url),
        )
        if cur.lastrowid and cur.rowcount:
            cap_id = cur.lastrowid
            c.executemany(
                "INSERT INTO capture_item (capture_id, section, sira, baslik, url) "
                "VALUES (?,?,?,?,?)",
                [(cap_id, it.section, it.sira, it.baslik, it.url) for it in cap.items],
            )
        else:  # zaten vardı
            cap_id = c.execute("SELECT id FROM capture WHERE basename = ?",
                               (cap.basename,)).fetchone()[0]
        c.commit()
        return cap_id

    # ---------- change (guid dedup) ----------
    def record_change(self, *, guid: str, rg_tarihi: str, rg_sayi: str, mukerrer: int,
                      section: str, baslik: str, url: str, is_degisiklik: bool,
                      matched_mevzuat_id: str | None, score: float | None,
                      target_extracted: str | None) -> bool:
        """Değişikliği kaydet; guid daha önce görülmüşse atla. Yeni ise True döner."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO change (guid, rg_tarihi, rg_sayi, mukerrer, section, "
            "baslik, url, is_degisiklik, matched_mevzuat_id, score, target_extracted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (guid, rg_tarihi, rg_sayi, mukerrer, section, baslik, url,
             int(is_degisiklik), matched_mevzuat_id, score, target_extracted),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def record_near_miss(self, *, guid: str, rg_tarihi: str, rg_sayi: str, mukerrer: int,
                         section: str, baslik: str, url: str,
                         candidate_mevzuat_id: str | None, score: float | None,
                         target_extracted: str | None) -> bool:
        """[80,90) bandını near_miss tablosuna yaz (guid dedup). Bilgi amaçlı, changes'e girmez."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO near_miss (guid, rg_tarihi, rg_sayi, mukerrer, section, "
            "baslik, url, candidate_mevzuat_id, score, target_extracted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (guid, rg_tarihi, rg_sayi, mukerrer, section, baslik, url,
             candidate_mevzuat_id, score, target_extracted),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def changes_window(self, days: int = 30) -> list[sqlite3.Row]:
        """Son `days` günde AUTO eşleşmiş değişiklikler (feed kayan penceresi)."""
        cur = self.conn.execute(
            "SELECT c.*, m.ad AS mevzuat_ad, m.rg_tarihi AS m_rg_tarihi "
            "FROM change c JOIN mevzuat m ON m.mevzuat_id = c.matched_mevzuat_id "
            "WHERE c.matched_mevzuat_id IS NOT NULL "
            "AND date(c.rg_tarihi) >= date('now', ?) "
            "ORDER BY c.rg_tarihi DESC, c.rg_sayi DESC",
            (f"-{int(days)} days",),
        )
        return cur.fetchall()


def default_seed_paths(root: str = ".") -> dict[str, str]:
    """Clean CSV'lerin yollarını (data/seed/ ya da kök) bul."""
    out = {}
    for key, name in (("mevzuat_csv", "Mevzuat_All.clean.csv"),
                      ("bolum_csv", "Bolum_List.clean.csv"),
                      ("madde_csv", "Madde_List.clean.csv")):
        for cand in (os.path.join(root, "data", "seed", name), os.path.join(root, name)):
            if os.path.exists(cand):
                out[key] = cand
                break
    return out
