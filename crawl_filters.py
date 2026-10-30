"""
تبدیل generic filters object (که با همان کلیدهای دیوار از پنل/cars-api می‌رسد) به
query params قابل اضافه‌شدن به URL دیوار.

فرمت ورودی مثال:
{ "production-year": {"min":1399,"max":1400}, "price": {"min":500000000},
  "usage": {"max":100000}, "has-photo": true, "recent_ads": "1d", "maxListings": 50 }

- number_range ({"min":..,"max":..}) => "key=min-max" (یا فقط یک طرف اگر دیگری نباشد)
- string/boolean => مستقیم "key=value" به query string اضافه می‌شود
- "maxListings" کلید مخصوص خود کرالر است (نه پارامتر دیوار) و روی max_items اثر می‌گذارد
- کلیدهای قدیمی year/productionYear/bodyStatus تا پایان مهاجرت داده‌ها پشتیبانی می‌شوند
  و به نام جدید دیوار (production-year/body_status) نگاشت می‌شوند
"""
from typing import Any, Dict, List, Optional, Tuple

LEGACY_KEY_MAP = {
    "year": "production-year",
    "productionYear": "production-year",
    "bodyStatus": "body_status",
}

BODY_STATUS_VALUE_MAP = {
    "سالم": "intact",
    "intact": "intact",
    "ضربه خورده": "other",
    "تصادفی": "other",
    "other": "other",
}

# fallback اگر GET /crawl-sources/divar/filters در دسترس نبود: فیلترهای چندانتخابی شناخته‌شده دیوار
FALLBACK_MULTI_SELECT_KEYS = {
    "body_status", "chassis_status", "motor_status", "color",
    "brand_model_manufacturer_origin", "fuel_type", "gearbox", "business-type",
}


def _format_number_range(value: Dict[str, Any]) -> Optional[str]:
    lo, hi = value.get("min"), value.get("max")
    if lo is not None and hi is not None:
        return f"{lo}-{hi}"
    if lo is not None:
        return f"{lo}-"
    if hi is not None:
        return f"-{hi}"
    return None


def _format_scalar(value: Any, is_multi_select: bool = False) -> str:
    if isinstance(value, bool):
        csv = "true" if value else "false"
    elif isinstance(value, (list, tuple)):
        csv = ",".join(str(v) for v in value)
    else:
        csv = str(value)
    # فیلترهای چندانتخابی دیوار با %2C در انتها فرستاده می‌شوند (مثل chassis_status=both-healthy%2C)
    return f"{csv}%2C" if is_multi_select else csv


def apply_filters(
    settings: Dict[str, Any],
    filters: Optional[Dict[str, Any]],
    multi_select_keys: Optional[set] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """settings را با extra_query_params پر می‌کند و لیست کلیدهای ورودی که پشتیبانی شدند را برمی‌گرداند."""
    extra_qs: Dict[str, str] = {}
    supported_keys: List[str] = []
    multi_select_keys = multi_select_keys if multi_select_keys is not None else FALLBACK_MULTI_SELECT_KEYS

    if not filters:
        settings["extra_query_params"] = extra_qs
        return settings, supported_keys

    for raw_key, value in filters.items():
        if raw_key == "maxListings":
            try:
                settings["max_items"] = int(value)
                supported_keys.append(raw_key)
            except (TypeError, ValueError):
                print(f"[~] مقدار نامعتبر برای maxListings: {value!r}")
            continue

        divar_key = LEGACY_KEY_MAP.get(raw_key, raw_key)
        if divar_key == "body_status" and not isinstance(value, dict):
            value = BODY_STATUS_VALUE_MAP.get(str(value).strip(), value)

        if isinstance(value, dict) and ("min" in value or "max" in value):
            qs_value = _format_number_range(value)
        else:
            qs_value = _format_scalar(value, is_multi_select=divar_key in multi_select_keys)

        if qs_value is None or qs_value == "":
            print(f"[~] فیلتر «{raw_key}» مقدار قابل‌استفاده‌ای ندارد و نادیده گرفته شد.")
            continue

        extra_qs[divar_key] = qs_value
        supported_keys.append(raw_key)

    settings["extra_query_params"] = extra_qs
    return settings, supported_keys
