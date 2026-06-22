# -*- coding: utf-8 -*-
"""RSS 2.0 feed üretici — Power Automate (SharePoint) tüketimi için.

Her <item> bir SharePoint satır-güncelleme operasyonudur:
  guid        = {MEV-ID}|{rg_tarih}|{rg_sayi}   (PA dedup anahtarı; URL DEĞİL)
  category    = AUTO
  pubDate     = RG tarihi (RFC-822)
  description = JSON: {table, id, fields:{isUpdated, updateDate, rgRef, rgUrl}}
Kanal atom:self-link içerir, kayan pencere (varsayılan son 30 gün).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from email.utils import format_datetime
from xml.sax.saxutils import escape

TZ_TR = dt.timezone(dt.timedelta(hours=3))   # Türkiye saati (+03:00)


@dataclass
class FeedItem:
    mevzuat_id: str
    mevzuat_ad: str
    rg_tarihi: str          # 'YYYY-MM-DD'
    rg_sayi: str
    rg_url: str
    mukerrer: int = 0

    @property
    def guid(self) -> str:
        # PA dedup anahtarı — aynı mevzuat + aynı RG sayısı tek operasyon
        return f"{self.mevzuat_id}|{self.rg_tarihi}|{self.rg_sayi}"

    def _rg_ref(self) -> str:
        try:
            d = dt.date.fromisoformat(self.rg_tarihi).strftime("%d.%m.%Y")
        except ValueError:
            d = self.rg_tarihi
        ref = f"RG {d}/{self.rg_sayi}" if self.rg_sayi else f"RG {d}"
        if self.mukerrer:
            ref += f" (Mükerrer {self.mukerrer})"
        return ref

    def description_json(self) -> str:
        payload = {
            "table": "Mevzuat_All",
            "id": self.mevzuat_id,
            "fields": {
                "isUpdated": True,
                "updateDate": self.rg_tarihi,
                "rgRef": self._rg_ref(),
                "rgUrl": self.rg_url,
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    def _pubdate(self) -> str:
        try:
            d = dt.date.fromisoformat(self.rg_tarihi)
        except ValueError:
            d = dt.date.today()
        return format_datetime(dt.datetime(d.year, d.month, d.day, tzinfo=TZ_TR))


def build_feed(items: list[FeedItem], *, self_url: str,
               title: str = "RG Mevzuat Değişiklik Takibi",
               site_url: str = "https://www.resmigazete.gov.tr/") -> str:
    """RSS 2.0 XML metni üret (atom:self-link dahil). Tüm metin XML-escape'lenir."""
    now = format_datetime(dt.datetime.now(TZ_TR))
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">')
    parts.append("  <channel>")
    parts.append(f"    <title>{escape(title)}</title>")
    parts.append(f"    <link>{escape(site_url)}</link>")
    parts.append(f"    <description>{escape('RG fihristinden otomatik (AUTO) eşleşen mevzuat değişiklikleri')}</description>")
    parts.append("    <language>tr</language>")
    parts.append(f"    <lastBuildDate>{now}</lastBuildDate>")
    parts.append(f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />')
    for it in items:
        parts.append("    <item>")
        parts.append(f"      <title>{escape(it.mevzuat_ad)}</title>")
        parts.append(f"      <link>{escape(it.rg_url)}</link>")
        parts.append(f'      <guid isPermaLink="false">{escape(it.guid)}</guid>')
        parts.append(f"      <category>AUTO</category>")
        parts.append(f"      <pubDate>{it._pubdate()}</pubDate>")
        parts.append(f"      <description>{escape(it.description_json())}</description>")
        parts.append("    </item>")
    parts.append("  </channel>")
    parts.append("</rss>")
    return "\n".join(parts) + "\n"


def items_from_changes(rows) -> list[FeedItem]:
    """db.changes_window() satırlarını FeedItem'a çevir."""
    out = []
    for r in rows:
        out.append(FeedItem(
            mevzuat_id=r["matched_mevzuat_id"],
            mevzuat_ad=r["mevzuat_ad"],
            rg_tarihi=r["rg_tarihi"],
            rg_sayi=r["rg_sayi"] or "",
            rg_url=r["url"],
            mukerrer=r["mukerrer"] or 0,
        ))
    return out


def write_feed(path: str | None = None, items: list[FeedItem] | None = None, *,
               self_url: str | None = None) -> str:
    """Feed'i diske yaz. path verilmezse config.FEED_OUT (docs/feed.xml) kullanılır."""
    import os
    if path is None or self_url is None:
        import config
        path = path or config.FEED_OUT
        self_url = self_url or config.FEED_SELF_URL
    xml = build_feed(items or [], self_url=self_url)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return path
