# -*- coding: utf-8 -*-
"""Proje genel ayarları."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

# Feed çıktısı: GitHub Pages "deploy from branch" yalnızca kök ya da /docs servis eder
# (/public servis edilmez) -> docs/feed.xml.
FEED_OUT = os.path.join(ROOT, "docs", "feed.xml")
FEED_SELF_URL = os.environ.get(
    "FEED_SELF_URL", "https://saglikyz.github.io/rg-compliance-mevzuat-takip/feed.xml"
)

# Eşleştirme kayan penceresi (gün)
FEED_WINDOW_DAYS = 30

# SQLite veritabanı
DB_PATH = os.path.join(ROOT, "rg_data.db")
