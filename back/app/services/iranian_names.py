"""Common Iranian given names (men / women) for OCR name validation."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.persian_text import normalize_persian


def _norm(name: str) -> str:
    """Fast normalize for lexicon keys (avoid per-name Hazm Normalizer cost)."""
    return normalize_persian(name).replace("‌", " ").strip()


# Frequent Iranian male given names (Persian script).
MALE_NAMES: Tuple[str, ...] = (
    "علی", "محمد", "حسین", "حسن", "رضا", "مهدی", "امیر", "احمد", "محمود", "عباس",
    "جواد", "سعید", "حمید", "وحید", "مجید", "فرهاد", "فرید", "کامران", "کیان", "کیانوش",
    "پیمان", "پویا", "پارسا", "پاشا", "داریوش", "داریو", "داریا", "داریان", "بهرام", "بهروز",
    "بهنام", "بهزاد", "بهشید", "بابک", "بیژن", "برزو", "آرش", "آرمان", "آرمین", "آریا",
    "آریو", "آریامن", "سیاوش", "سیامک", "سینا", "سامان", "سام", "سهراب", "سهیل", "سورنا",
    "سوریا", "شهرام", "شهریار", "شهاب", "شاهین", "شایان", "شروین", "نیما", "نوید", "ناصر",
    "نادر", "میلاد", "مهران", "مهرداد", "مسعود", "مصطفی", "محسن", "مرتضی", "مجتبی", "مازیار",
    "کاوه", "کوروش", "کیومرث", "کیوان", "ایمان", "اسماعیل", "ابراهیم", "اسحاق", "یوسف", "یعقوب",
    "یونس", "یحیی", "هادی", "هومن", "هومن", "هوشنگ", "هرمز", "همایون", "فرزاد", "فرزین",
    "فرشید", "فرهنگ", "فرامرز", "فربد", "علیرضا", "امیرحسین", "امیررضا", "امیرمحمد", "محمدعلی",
    "محمدحسین", "محمدرضا", "محمدرضا", "سیدعلی", "سیدحسین", "سیدرضا", "سیدمحمد", "ابوالفضل",
    "ابوالقاسم", "قاسم", "قاسمعلی", "اصغر", "اکبر", "افشین", "اردشیر", "اردوان", "ارژنگ",
    "ارشیا", "امید", "انوشیروان", "انوشه", "ایوب", "ایلیا", "پدرام", "پژمان", "پیام", "جاوید",
    "جمشید", "جهانگیر", "جهانبخش", "حامد", "حبیب", "حکیم", "خلیل", "داریوش", "رادین", "رادمان",
    "رامتین", "رامین", "رستم", "روزبه", "سالار", "سروش", "سهراب", "شایان", "صدرا", "طاها",
    "طاهر", "عارف", "عرفان", "عزت", "علی‌اکبر", "علی‌اصغر", "علی‌رضا", "غلامرضا", "غلامحسین",
    "فاتح", "فریدون", "قاسم", "لئون", "مانوئل", "مانی", "مانی", "مبین", "متین", "محراب",
    "مراد", "مرصاد", "مصطفی", "معین", "مهدیار", "مهیار", "نریمان", "نوذر", "نیکان", "هومن",
    "یاسر", "یاشار", "یوسف", "کسری", "کیارش", "کیان", "آرین", "آرمین", "آراد", "آریوبرزن",
)

# Frequent Iranian female given names (Persian script).
FEMALE_NAMES: Tuple[str, ...] = (
    "فاطمه", "زهرا", "زینب", "مریم", "معصومه", "سکینه", "خدیجه", "رقیه", "صدیقه", "طاهره",
    "نرگس", "نازنین", "نازیلا", "نیلوفر", "نیوشا", "نگار", "نغمه", "نسیم", "نسرین", "نیکو",
    "مهسا", "مهناز", "مهتاب", "مهری", "مهشید", "مهناز", "میترا", "مینا", "مینا", "مونا",
    "منیر", "منصوره", "ملیحه", "ملیکا", "ملینا", "مارال", "مانا", "ماندانا", "مائده", "لیلا",
    "لیلا", "لیلای", "لیدا", "لادن", "کیانا", "کیمیا", "کتایون", "گلناز", "گلرخ", "گلاره",
    "گیتا", "گیسو", "فروغ", "فرشته", "فرناز", "فریده", "فریبا", "فریماه", "فرانک", "فاطمه",
    "شیرین", "شیوا", "شهلا", "شهناز", "شهرزاد", "شیدا", "شبنم", "سمیرا", "سمیه", "سارا",
    "سارینه", "ساناز", "سپیده", "ستاره", "سودابه", "سوسن", "سوفیا", "سیما", "سیمین", "سحر",
    "زهرا", "زری", "زریناز", "رویا", "روژین", "رعنا", "راضیه", "راحله", "راحیل", "پریسا",
    "پریناز", "پریچهر", "پگاه", "پونه", "پوپک", "آتنا", "آتوسا", "آزاده", "آزیتا", "آیدا",
    "آیلار", "آیلین", "آیسان", "آناهیتا", "آنیسا", "الهام", "الناز", "الهه", "انسیه", "ایران",
    "بهار", "بهاره", "بهناز", "بهنوش", "تارا", "ترانه", "ترنم", "تکتم", "جمیله", "حکیمه",
    "حنانه", "حوریه", "دیبا", "دلارام", "دلارا", "رومینا", "ژیلا", "ژینا", "سوزان", "شقایق",
    "شیما", "صبا", "صنم", "طیبه", "عسل", "غزل", "فتانه", "فرزانه", "فرگل", "کتایون",
    "گلشن", "گلنار", "لاله", "ماه‌لقا", "مرجان", "مرضیه", "مژگان", "مژده", "مهین", "میهن",
    "نسرین", "نفیسه", "نوژان", "نوید", "هاله", "هستی", "هلن", "هما", "هنگامه", "هانیه",
    "یاسمن", "یاسمین", "یگانه", "یلدا", "یگانه", "ویدا", "ویدا", "ویکتوریا", "ژیلا",
)

_MALE_SET = {_norm(n) for n in MALE_NAMES if n.strip()}
_FEMALE_SET = {_norm(n) for n in FEMALE_NAMES if n.strip()}
_ALL: Dict[str, str] = {}
for name in _MALE_SET:
    _ALL[name] = "male"
for name in _FEMALE_SET:
    # Prefer male if a rare overlap exists (e.g. نوید).
    _ALL.setdefault(name, "female")


@dataclass
class LexiconMatch:
    name: str
    gender: str  # male | female | unknown
    similarity: float
    is_exact: bool


def canon_name(value: str) -> str:
    text = _norm(value or "")
    return text.replace("آ", "ا").replace("‌", "").replace(" ", "")


def gender_of(name: str) -> str:
    cleaned = _norm(name or "")
    if cleaned in _MALE_SET and cleaned in _FEMALE_SET:
        return "unknown"
    if cleaned in _MALE_SET:
        return "male"
    if cleaned in _FEMALE_SET:
        return "female"
    return "unknown"


def is_known_iranian_name(name: str) -> bool:
    cleaned = _norm(name or "")
    return cleaned in _ALL


def all_names(*, gender: Optional[str] = None) -> List[str]:
    if gender == "male":
        return sorted(_MALE_SET)
    if gender == "female":
        return sorted(_FEMALE_SET)
    return sorted(_ALL.keys())


def best_lexicon_matches(
    raw: str,
    *,
    limit: int = 5,
    threshold: float = 62.0,
    prefer_gender: Optional[str] = None,
) -> List[LexiconMatch]:
    """Fuzzy match OCR / Nasta'liq noise against Iranian given names."""
    cleaned = _norm(raw or "")
    if not cleaned:
        return []

    if cleaned in _ALL:
        return [
            LexiconMatch(
                name=cleaned,
                gender=_ALL[cleaned],
                similarity=100.0,
                is_exact=True,
            )
        ]

    needle = canon_name(cleaned)
    scored: List[LexiconMatch] = []
    pool = _ALL.items()
    for name, gender in pool:
        if prefer_gender and gender != prefer_gender and gender != "unknown":
            # Soft prefer — still allow other gender, slightly lower later.
            pass
        ratio = SequenceMatcher(None, needle, canon_name(name)).ratio() * 100.0
        # Bonus for shared prefix (common in Nasta'liq misreads).
        if needle and name and needle[0] == name[0]:
            ratio = min(100.0, ratio + 3.0)
        if prefer_gender and gender == prefer_gender:
            ratio = min(100.0, ratio + 2.0)
        if ratio >= threshold:
            scored.append(
                LexiconMatch(
                    name=name,
                    gender=gender,
                    similarity=round(ratio, 1),
                    is_exact=False,
                )
            )
    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:limit]


def compare_to_lexicon(
    names: Sequence[str], *, threshold: float = 70.0
) -> List[Dict[str, object]]:
    """Compare extracted names to closest Iranian lexicon entries."""
    rows: List[Dict[str, object]] = []
    for raw in names:
        cleaned = _norm(raw or "")
        if not cleaned:
            continue
        matches = best_lexicon_matches(cleaned, limit=3, threshold=threshold)
        if not matches:
            rows.append(
                {
                    "raw": cleaned,
                    "valid_name": "",
                    "gender": "unknown",
                    "similarity": 0.0,
                    "is_valid": False,
                }
            )
            continue
        top = matches[0]
        rows.append(
            {
                "raw": cleaned,
                "valid_name": top.name,
                "gender": top.gender,
                "similarity": top.similarity,
                "is_valid": top.is_exact or top.similarity >= 90.0,
                "alternatives": [
                    {"name": m.name, "gender": m.gender, "similarity": m.similarity}
                    for m in matches[1:]
                ],
            }
        )
    return rows
