# rg-compliance-mevzuat-takip

Resmî Gazete günlük fihristinden, izlenen mevzuat kataloğundaki (rg_yayinlanir=True) değişiklikleri
otomatik yakalayıp bir RSS feed'i (`docs/feed.xml`) üreten uyum takip sistemi.

## Bileşenler
- `rg/scraper.py` — günlük fihrist parser (windows-1254) + tamlık doğrulama (probe).
- `rg/db.py` — SQLite, 4 katman (mevzuat→bölüm→madde→fıkra) + capture/change/near_miss.
- `rg/matcher.py` — rapidfuzz eşleştirme (AUTO ≥90, near-miss [80,90)).
- `rg/feed.py` — Power Automate (SharePoint) için RSS 2.0 üretici.
- `scripts/test_pipeline.py` — uçtan uca doğrulama/regresyon testi.
- `scripts/push_feed.py` — feed'i GitHub'a yükleyen iskelet.

## Feed
`docs/feed.xml` GitHub Pages ile yayımlanır. Her `<item>` bir SharePoint satır-güncelleme
operasyonudur (`guid = {MEV-ID}|{rg_tarih}|{rg_sayi}`).

> Not: Seed CSV'leri (`Mevzuat_All*.csv` vb.) `.gitignore` ile hariç tutulur; SharePoint
> source of truth'tur.
