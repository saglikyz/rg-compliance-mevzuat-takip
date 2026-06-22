# RG Compliance Mevzuat Takip — Claude Code Bağlamı

## Proje Amacı
Resmî Gazete'yi günlük scrape edip takip edilen mevzuatlardaki değişiklikleri
tespit et, RSS feed üret (GitHub Pages), Power Automate bu feed'i dinleyip
SharePoint listelerini güncellesin.

## Kaynak
POST https://www.resmigazete.gov.tr/Home/Filter (JSON API, DataTables server-side)
Request body: {draw, start, length, parameters:{genelBaslangicTarihi, genelBitisTarihi, searchtype:1, mevzuatTuru:""}}

## SharePoint Hiyerarşisi (ID zinciri)
Mevzuat_All   MEV-002
Bolum_List    MEV-002-B02
Madde_List    MEV-002-B02-M012
Fikra_List    MEV-002-B02-M012-F001

## Klasör Yapısı
rg/          → scraper, db, matcher, feed modülleri
matcher/     → fuzzy eşleştirme
feed/        → RSS üretici
db/          → SQLite (rg_state.db)
archive/     → günlük ham JSON
logs/        → scrape + eşleştirme logları
public/      → feed.xml (GitHub Pages'te yayınlanır)

## Kurallar
- Sadece BelgeTürü=Mevzuat olanlar izlenir (51 kayıt). Kılavuzlar kapsam dışı.
- Eşleştirme eşiği: ≥90 AUTO (otomatik), <90 yoksay+logla. REVIEW yok.
- PA'da sadece standart connector (RSS + SharePoint + Teams). Premium yok.
- Feed: kayan pencere 30 gün, guid ile dedup.

## RSS Sözleşmesi
Her item = bir SharePoint satır-güncelleme operasyonu
- guid     → {id}|{tarih}|{sayı}
- category → AUTO
- description → JSON: {table, id, fields:{isUpdated, updateDate, rgRef, rgUrl}}

## Faz Planı
- Faz 1: Mevzuat_All → isUpdated + updateDate + RG referansı
- Faz 2: Fikra_List  → FikraIcerik + FikraMetniHTML güncelleme