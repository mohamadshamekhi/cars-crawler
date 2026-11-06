"""استخراج شهر/استان آگهی از HTML یا JSON خام دیوار (تابع خالص، بدون Playwright).

دیوار موقعیت مکانی هر آگهی را در یک شیء ``city`` نگه می‌دارد که هم داخل state
امبدشده‌ی صفحه‌ی آگهی (``window.__PRELOADED_STATE__``) هست و هم در پاسخ API دیوار
(``api.divar.ir/v8/posts-v2/web/<token>``) — با دو شکل کمی متفاوت:

    HTML state : {"id": "1", "slug": "tehran", "parent": "904", "name": "تهران"}
    API JSON   : {"city_id": "1", "name": "تهران", "parent_id": "904", "second_slug": "tehran"}

``id``/``city_id`` دقیقاً همان cityDivarId مورد نیاز cars-api است و ``parent``/``parent_id``
همان provinceDivarId (شناسه‌ی استان در درخت مکان دیوار). مثل divar_description.py، استخراج
از HTML با regex روی متن خام اسکریپت‌ها انجام می‌شود (نه json.loads کامل state که حجیم و
گاهی ناقص است)؛ استخراج از JSON آگهی با پیمایش بازگشتی دیکشنری.

اگر هیچ‌کدام جواب نداد (ساختار دیوار عوض شده، یا آگهی بدون شهر) دیکشنری خالی برمی‌گردد —
این داده اختیاری است و نبودش کرال را نباید متوقف کند.
"""

import json
import re
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup

# شیء city داخل state امبدشده‌ی صفحه؛ ترتیب کلیدها تضمینی نیست، هر فیلد جدا پیدا می‌شود
_CITY_OBJECT_RE = re.compile(r'"city"\s*:\s*\{([^}]*)\}')
_CITY_ID_RE = re.compile(r'"id"\s*:\s*"?(\d+)"?')
_CITY_PARENT_RE = re.compile(r'"parent"\s*:\s*"?(\d+)"?')
_CITY_NAME_RE = re.compile(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _unescape(text: str) -> str:
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text


def _parse_city_fragment(fragment: str) -> Optional[Dict[str, Any]]:
    id_match = _CITY_ID_RE.search(fragment)
    if not id_match:
        return None
    result: Dict[str, Any] = {"city_divar_id": id_match.group(1)}
    parent_match = _CITY_PARENT_RE.search(fragment)
    if parent_match:
        result["province_divar_id"] = parent_match.group(1)
    name_match = _CITY_NAME_RE.search(fragment)
    if name_match:
        name = _unescape(name_match.group(1)).strip()
        if name:
            result["city_name"] = name
    return result


def location_from_html(soup: BeautifulSoup) -> Dict[str, Any]:
    """جستجوی شیء city در تمام <script>های صفحه (مستقل از نام متغیر JS)."""
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if '"city"' not in raw:
            continue
        for match in _CITY_OBJECT_RE.finditer(raw):
            parsed = _parse_city_fragment(match.group(1))
            if parsed:
                return parsed
    return {}


def _find_city_dict(data: Any) -> Optional[Dict[str, Any]]:
    """دیکشنری city در JSON آگهی دیوار: دارای city_id و name و parent_id با هم
    (برای فرار از city_id های پراکنده‌ی دیگر که فقط یک عدد خام‌اند، نه شیء مکان)."""
    if isinstance(data, dict):
        if "city_id" in data and "name" in data and "parent_id" in data:
            return data
        for value in data.values():
            found = _find_city_dict(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_city_dict(value)
            if found:
                return found
    return None


def location_from_post_json(data: Any) -> Dict[str, Any]:
    """شیء city از JSON آگهی دیوار (پاسخ API یا state صفحه)؛ دیکشنری خالی اگر نبود."""
    city = _find_city_dict(data)
    if not city:
        return {}
    result: Dict[str, Any] = {}
    city_id = city.get("city_id")
    if city_id:
        result["city_divar_id"] = str(city_id)
    parent_id = city.get("parent_id")
    if parent_id:
        result["province_divar_id"] = str(parent_id)
    name = city.get("name")
    if isinstance(name, str) and name.strip():
        result["city_name"] = name.strip()
    return result


def extract_location(soup: BeautifulSoup, post_json: Any = None) -> Dict[str, Any]:
    """اول HTML؛ اگر پیدا نشد و JSON آگهی (از API توضیحات) موجود بود، از آن."""
    location = location_from_html(soup)
    if location:
        return location
    if post_json is not None:
        return location_from_post_json(post_json)
    return {}
