"""استخراج توضیحات آگهی دیوار از HTML صفحه‌ی آگهی (تابع خالص، بدون Playwright).

دیوار هر چند وقت کلاس‌های CSS را عوض می‌کند و وابستگی به یک کلاس باعث می‌شد توضیحات بی‌صدا
خالی بماند. چند راه مستقل به ترتیب امتحان می‌شوند و اولین متن معتبر برمی‌گردد:

1. پاراگراف `kt-description-row__text` (ساختار قدیمی/فعلی)
2. بخشی که عنوانش دقیقاً «توضیحات» است (مستقل از نام کلاس)
3. داده‌ی JSON داخل صفحه (state سرور دیوار): ویجت `DESCRIPTION_ROW` و text آن
4. JSON-LD ‏(`<script type="application/ld+json">`) با کلید description
5. متای `og:description` / `description`

اگر هیچ‌کدام جواب نداد، car_scraper همان آگهی را از API دیوار
(`api.divar.ir/v8/posts-v2/web/<token>`) می‌خواند: `description_from_post_json`.
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


# ویجت توضیحات در JSON دیوار (صفحه و API): {"widget_type": "DESCRIPTION_ROW", "data": {"text": "..."}}
_DESCRIPTION_WIDGET = re.compile(r'DESCRIPTION_ROW|DescriptionRowData')
_TEXT_FIELD = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
# فاصله‌ی مجاز بین نام ویجت و فیلد text (هر دو داخل همان ویجت)
_WIDGET_WINDOW = 600


def _widget_text(container: Any) -> Optional[str]:
    """جستجوی بازگشتی ویجت DESCRIPTION_ROW در JSON پارس‌شده."""
    if isinstance(container, dict):
        if container.get("widget_type") == "DESCRIPTION_ROW":
            data = container.get("data")
            text = data.get("text") if isinstance(data, dict) else None
            if isinstance(text, str) and text.strip():
                return text
        for v in container.values():
            found = _widget_text(v)
            if found:
                return found
    elif isinstance(container, list):
        for v in container:
            found = _widget_text(v)
            if found:
                return found
    return None


def description_from_post_json(data: Any) -> str:
    """توضیحات از JSON آگهی دیوار (پاسخ API یا state صفحه)؛ رشته‌ی خالی اگر نبود."""
    text = _widget_text(data)
    return _clean(text) if text else ""


def _from_embedded_state(soup: BeautifulSoup) -> Optional[str]:
    """state سرور دیوار داخل <script> (مستقل از HTML رندرشده و کلاس‌ها)."""
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not _DESCRIPTION_WIDGET.search(raw):
            continue
        # JSON داخل رشته‌ی JS (JSON.parse("...")) ⇒ یک لایه escape
        variants = [raw, re.sub(r'\\(["\\/])', r'\1', raw)] if '\\"' in raw else [raw]
        for text in variants:
            for widget in _DESCRIPTION_WIDGET.finditer(text):
                window = text[max(0, widget.start() - _WIDGET_WINDOW): widget.end() + _WIDGET_WINDOW]
                # نزدیک‌ترین text بعد از نام ویجت، وگرنه قبل از آن
                after = _TEXT_FIELD.search(text, widget.end(), widget.end() + _WIDGET_WINDOW)
                match = after or (list(_TEXT_FIELD.finditer(window)) or [None])[-1]
                if not match:
                    continue
                try:
                    value = json.loads(f'"{match.group(1)}"')
                except ValueError:
                    continue
                if isinstance(value, str) and _clean(value):
                    return _clean(value)
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
    for strategy in (_from_description_rows, _from_heading, _from_embedded_state, _from_json_ld, _from_meta):
        text = strategy(soup)
        if text:
            return text
    return ""
