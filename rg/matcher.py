# -*- coding: utf-8 -*-
"""RG fihrist başlıklarını mevzuat kataloğuyla eşleştirme.

rapidfuzz token_set_ratio; skor >= AUTO_THRESHOLD ise otomatik eşleşme,
altı yok sayılır (loglanır). "Değişiklik Yapılmasına Dair" başlıklarında
değiştirilen mevzuatın adı ayıklanıp onunla eşleştirilir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

log = logging.getLogger("rg.matcher")

AUTO_THRESHOLD = 90.0      # >= : otomatik eşleşme (changes'e girer)
NEAR_THRESHOLD = 80.0      # [80, 90) : near-miss (sadece görünürlük, changes'e GİRMEZ)

_DEGISIKLIK_RE = re.compile(r"Değişiklik\s+Yapılmasına\s+(?:Dair|İlişkin)", re.I)
_RG_REF_RE = re.compile(r"\bRG\s*\d{2}\.\d{2}\.\d{4}\s*/\s*\d+", re.I)
_TEBLIG_NO_RE = re.compile(r"\((?:TEBLİĞ\s*)?NO\s*:?[^)]*\)", re.I)

# Hukuki belge-tipi kelimelerinin çekimli hâllerini köke indir (her iki tarafa da
# uygulanır; "Yönetmeliğinde"->"yönetmelik", "Kanunda"->"kanun" gibi). Türkçe ünsüz
# yumuşaması (k->ğ) nedeniyle ayrı kalıplar gerekir.
_CANON = [
    (re.compile(r"\byönetmeli(?:k|ğin(?:de|den)?|ği|ğe)\b", re.I), "yönetmelik"),
    (re.compile(r"\bkanun(?:un(?:da|dan)?|da|dan|u|a)?\b", re.I), "kanun"),
    (re.compile(r"\bkararname(?:sin(?:de|den)?|si|ye)?\b", re.I), "kararname"),
    (re.compile(r"\btebliğ(?:in(?:de|den)?|i|e)?\b", re.I), "tebliğ"),
    (re.compile(r"\bkarar(?:ın(?:da|dan)?|ı|a)?\b", re.I), "karar"),
    (re.compile(r"\bgenelge(?:sin(?:de|den)?|si|ye)?\b", re.I), "genelge"),
]


def is_degisiklik(baslik: str) -> bool:
    return bool(_DEGISIKLIK_RE.search(baslik))


def normalize(s: str) -> str:
    s = _RG_REF_RE.sub(" ", s)
    s = _TEBLIG_NO_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    for pat, rep in _CANON:
        s = pat.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_target(baslik: str) -> str:
    """'X'te Değişiklik Yapılmasına Dair ...' -> 'X' (değiştirilen mevzuat adı).

    Değişiklik kalıbı yoksa başlığın tamamı döner (doğrudan ad eşleşmesi denenir).
    Çekim ekleri burada kırpılmaz; normalize() içinde her iki tarafta kanonikleşir.
    """
    m = _DEGISIKLIK_RE.search(baslik)
    if not m:
        return baslik.strip()
    target = baslik[:m.start()].strip()
    # baştaki sıra no / kod artıkları
    target = re.sub(r"^\s*(\d+|[–-]{2,})\s*", "", target).strip()
    return target.strip()


@dataclass
class MatchResult:
    baslik: str
    is_degisiklik: bool
    target: str
    matched_mevzuat_id: str | None    # yalnızca AUTO bandında dolu
    matched_ad: str | None
    score: float
    band: str           # 'auto' (>=90) | 'near_miss' [80,90) | 'ignore' (<80)
    top3: list[tuple[str, float]]

    @property
    def auto(self) -> bool:
        return self.band == "auto"

    @property
    def near_miss(self) -> bool:
        return self.band == "near_miss"

    # near-miss/ignore bandında bile en iyi adayı görebilmek için
    best_id: str | None = None


class Matcher:
    def __init__(self, catalog: list[tuple[str, str]],
                 auto_threshold: float = AUTO_THRESHOLD,
                 near_threshold: float = NEAR_THRESHOLD):
        """catalog: [(mevzuat_id, ad), ...] — yalnızca rg_yayinlanir=True olanlar."""
        self.auto_threshold = auto_threshold
        self.near_threshold = near_threshold
        self._ids = [mid for mid, _ in catalog]
        # normalize edilmiş ad -> id eşlemesi (process.extract için dict)
        self._choices = {mid: normalize(ad) for mid, ad in catalog}
        self._ad = {mid: ad for mid, ad in catalog}

    def match(self, baslik: str) -> MatchResult:
        deg = is_degisiklik(baslik)
        target = extract_target(baslik)
        ntarget = normalize(target)
        ranked = process.extract(
            ntarget, self._choices, scorer=fuzz.token_set_ratio, limit=3
        )  # [(normalized_ad, score, mevzuat_id), ...]
        top3 = [(r[2], round(r[1], 1)) for r in ranked]
        if ranked:
            best_score, best_id = ranked[0][1], ranked[0][2]
        else:
            best_score, best_id = 0.0, None
        if best_score >= self.auto_threshold:
            band = "auto"
        elif best_score >= self.near_threshold:
            band = "near_miss"
            log.info("near-miss (%.1f) [%s] %s", best_score, best_id, baslik[:70])
        else:
            band = "ignore"
        return MatchResult(
            baslik=baslik, is_degisiklik=deg, target=target,
            matched_mevzuat_id=best_id if band == "auto" else None,
            matched_ad=self._ad.get(best_id) if band == "auto" else None,
            score=round(best_score, 1), band=band, top3=top3, best_id=best_id,
        )
