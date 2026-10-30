"""استخراج توضیحات آگهی دیوار از HTML صفحه‌ی آگهی (تابع خالص، بدون Playwright).

دیوار هر چند وقت کلاس‌های CSS را عوض می‌کند و وابستگی به یک کلاس باعث می‌شد توضیحات بی‌صدا
خالی بماند. چند راه مستقل به ترتیب امتحان می‌شوند و اولین متن معتبر برمی‌گردد:

1. پاراگراف `kt-description-row__text` (ساختار قدیمی/فعلی)
2. بخشی که عنوانش دقیقاً «توضیحات» است (مستقل از نام کلاس)
3. JSON-LD ‏(`<script type="application/ld+json">`) با کلید description
4. متای `og:description` / `description`
"""

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

DESCRIPTION_HEADING = "توضیحات"
# ردیف‌های تاریخ که در همان کامپوننت توضیحات رندر می‌شوند
_DATE_MARKERS = ("انتشار آگهی", "آخرین به‌روز‌رسانی", "آخرین به‌روزرسانی")
# عنوان بخش‌های دیگر صفحه: رسیدن به این‌ها یعنی بخش توضیحات تمام شده
_SECTION_TITLES = {"ارزیابی فروشنده", "بررسی و کارشناسی", "ارزیابی قیمت", "گزارش آگهی", "نقشه"}
_BLOCK_TAGS = {"p", "div", "span", "section", "article"}


def _clean(text: str) -> str:
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _is_date_text(text: str) -> bool:
    return any(marker in text for marker in _DATE_MARKERS)


def _from_description_rows(soup: BeautifulSoup) -> Optional[str]:
    texts = []
    for p in soup.find_all("p", class_=re.compile("kt-description-row__text")):
        txt = _clean(p.get_text(separator="\n"))
        if txt and not _is_date_text(txt):
            texts.append(txt)
    return "\n".join(texts) if texts else None


def _from_heading(soup: BeautifulSoup) -> Optional[str]:
    """اولین بلوک متنی بعد از عنوان «توضیحات» (هر تگ و هر کلاسی)."""
    for heading in soup.find_all(string=re.compile(rf"^\s*{DESCRIPTION_HEADING}\s*$")):
        node = heading.parent
        if not isinstance(node, Tag):
            continue
        for el in node.find_all_next():
            if not isinstance(el, Tag):
                continue
            # تگ‌ها/دسته‌بندی‌های پایین بخش (لینک) یا بخش بعدی ⇒ پایان
            if el.name == "a" or el.name in ("h1", "h2", "h3", "h4"):
                txt = el.get_text(strip=True)
                if el.name == "a" or txt in _SECTION_TITLES or txt != DESCRIPTION_HEADING:
                    break
            if el.name not in _BLOCK_TAGS:
                continue
            # بلوکِ حاوی لینک = تگ‌های دسته‌بندی پایین بخش ⇒ پایان توضیحات
            if el.find("a"):
                break
            # فقط بلوک برگ‌مانند (بدون بلوک تو در تو) تا متن کل صفحه جمع نشود
            if el.find(list(_BLOCK_TAGS)):
                continue
            txt = _clean(el.get_text(separator="\n"))
            if not txt or txt == DESCRIPTION_HEADING:
                continue
            if txt in _SECTION_TITLES:
                break
            if _is_date_text(txt):
                continue
            return txt
    return None


def _find_key(data: Any, key: str) -> Optional[str]:
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
        for v in data.values():
            found = _find_key(v, key)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _find_key(v, key)
            if found:
                return found
    return None


def _from_json_ld(soup: BeautifulSoup) -> Optional[str]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (ValueError, TypeError):
            continue
        found = _find_key(data, "description")
        if found:
            return _clean(found)
    return None


def _from_meta(soup: BeautifulSoup) -> Optional[str]:
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        meta = soup.find("meta", attrs=attrs)
        content = meta.get("content") if meta else None
        if isinstance(content, str) and content.strip():
            return _clean(content)
    return None


def extract_description(soup: BeautifulSoup) -> str:
    """متن توضیحات یا رشته‌ی خالی اگر هیچ راهی جواب نداد."""
    for strategy in (_from_description_rows, _from_heading, _from_json_ld, _from_meta):
        text = strategy(soup)
        if text:
            return text
    return ""
