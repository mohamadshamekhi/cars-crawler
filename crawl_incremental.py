"""
منطق خالص کرال incremental (بدون مرورگر/شبکه تا تست‌پذیر باشد).

برای هر کارت لیست دیوار (token + قیمت کارت):
- token جدید یا قیمت متفاوت/نامعلوم ⇒ باز کردن صفحه‌ی آگهی و ارسال snapshot کامل (شمارنده‌ی K صفر می‌شود)
- شناخته‌شده و بدون تغییر ⇒ token در batch «seen» جمع می‌شود و شمارنده‌ی K یکی بالا می‌رود
- K کارت پشت‌سرهم شناخته‌شده و بدون تغییر ⇒ توقف زودهنگام (stoppedEarly)
"""
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

SEEN_BATCH_MAX = 1000
DEFAULT_STOP_AFTER_KNOWN = 20

_DIGIT_TABLE = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class RunNotRunningError(Exception):
    """cars-api با 409 و code=run_not_running جواب داد: ران تمام/timeout شده و کرال باید تمیز متوقف شود."""


def normalize_price(value: Any) -> Optional[int]:
    """«۳,۰۵۰,۰۰۰,۰۰۰ تومان» / «3٬050٬000٬000» / 3050000000 ⇒ 3050000000؛ ناخوانا/توافقی/None ⇒ None"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    digits = re.sub(r"\D", "", str(value).translate(_DIGIT_TABLE))
    if not digits:
        return None
    number = int(digits)
    return number if number > 0 else None


def token_from_url(url: str) -> str:
    """توکن آگهی دیوار = آخرین بخش مسیر URL (مثلاً /v/<slug>/gaf72dJB ⇒ gaf72dJB)"""
    path = urlparse(url).path if "://" in url else url.split("?", 1)[0]
    return path.rstrip("/").rsplit("/", 1)[-1]


def chunk(items: List[str], size: int = SEEN_BATCH_MAX) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


class IncrementalTracker:
    def __init__(self, known_items: Iterable[Dict[str, Any]], stop_after_known: int = DEFAULT_STOP_AFTER_KNOWN):
        self.known: Dict[str, Optional[int]] = {}
        for item in known_items or []:
            token = item.get("token")
            if token:
                self.known[str(token)] = normalize_price(item.get("price"))
        self.stop_after_known = max(1, int(stop_after_known or DEFAULT_STOP_AFTER_KNOWN))
        self.consecutive_known = 0
        self.pending_seen: List[str] = []
        self.stats = {"new": 0, "changed": 0, "unchanged": 0, "unknown": 0}

    def classify(self, token: str, card_price: Any) -> str:
        """'new' | 'changed' | 'unchanged' (truncated: هر token خارج لیست جدید است)"""
        if token not in self.known:
            return "new"
        known_price = self.known[token]
        price = normalize_price(card_price)
        if price is None or known_price is None or price != known_price:
            return "changed"
        return "unchanged"

    def observe(self, token: str, card_price: Any) -> str:
        """ثبت یک کارت؛ خروجی همان classify. unchanged ⇒ به seen اضافه و شمارنده +۱؛ بقیه ⇒ شمارنده صفر."""
        kind = self.classify(token, card_price)
        self.stats[kind] += 1
        if kind == "unchanged":
            self.consecutive_known += 1
            if token not in self.pending_seen:
                self.pending_seen.append(token)
        else:
            self.consecutive_known = 0
        return kind

    @property
    def should_stop(self) -> bool:
        return self.consecutive_known >= self.stop_after_known

    def take_seen_batch(self, force: bool = False) -> List[str]:
        """یک batch آماده‌ی ارسال (≤۱۰۰۰)؛ بدون force فقط وقتی batch پر شده باشد"""
        if not self.pending_seen or (not force and len(self.pending_seen) < SEEN_BATCH_MAX):
            return []
        batch, self.pending_seen = self.pending_seen[:SEEN_BATCH_MAX], self.pending_seen[SEEN_BATCH_MAX:]
        return batch

    def summary(self, mode: str, stopped_early: bool) -> str:
        s = self.stats
        return (f"mode={mode} new={s['new']} changed={s['changed']} unchanged={s['unchanged']} "
                f"unknown={s['unknown']} stoppedEarly={stopped_early}")
