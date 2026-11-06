"""کرال قیمت خودروی صفر از همراه‌مکانیک (https://www.hamrah-mechanic.com/carprice/).

صفحه SSR (Next.js) است؛ داده از <script id="__NEXT_DATA__"> خوانده می‌شود و فقط در صورت نبودِ آن
به Playwright برمی‌گردیم. اجرای دستی (بدون تریگر بک‌اند): python new_car_prices.py
"""
import asyncio
import json
import os
import re
import ssl
import sys
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import httpx

from crawl_incremental import RunNotRunningError

DEFAULT_SOURCE = "hamrah-mechanic"
DEFAULT_URL = "https://www.hamrah-mechanic.com/carprice/"
ITEMS_BATCH_MAX = 100  # بدنه‌ی JSON باید زیر سقف ۱۰۰KB پیش‌فرض body-parser در cars-api بماند
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# سرور همراه‌مکانیک intermediate را در handshake نمی‌فرستد (chain ناقص)؛ مرورگر/curl با AIA پیدایش می‌کنند
# ولی OpenSSL پایتون نه. intermediate (Certum DV TLS G2 R39 CA، تا ۲۰۳۹) کنار certifi لود می‌شود؛ verify خاموش نیست.
EXTRA_CA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "certum_dv_tls_g2_r39_ca.pem")

_NEXT_DATA_RE = re.compile(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S)
_WS_RE = re.compile(r"\s+")


class NextDataNotFoundError(Exception):
    """صفحه __NEXT_DATA__ معتبر ندارد (SSR نشده یا ساختار عوض شده)."""


def extract_next_data(html: str) -> Dict[str, Any]:
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        raise NextDataNotFoundError("__NEXT_DATA__ در صفحه پیدا نشد")
    try:
        return json.loads(m.group(1))
    except ValueError as e:
        raise NextDataNotFoundError(f"__NEXT_DATA__ قابل parse نیست: {e}") from e


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = _WS_RE.sub(" ", str(v)).strip()
    return s or None


def _to_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _brand_url(page_url: str, brand_en: Optional[str]) -> Optional[str]:
    if not brand_en:
        return None
    base = page_url if page_url.endswith("/") else page_url + "/"
    return urljoin(base, f"{brand_en.strip().lower()}/")


def map_row(row: Dict[str, Any], brand: Dict[str, Any], page_url: str) -> Optional[Dict[str, Any]]:
    """یک ردیف carPriceOnBrandDetails ⇒ آیتم cars-api؛ فقط فیلدهای قرارداد، بدون null. بدون brand/model ⇒ None."""
    brand_name = _clean(row.get("brandName")) or _clean(brand.get("brandName"))
    model = _clean(row.get("modelName"))
    if not brand_name or not model:
        return None
    brand_en = _clean(row.get("brandEnglishName"))
    item: Dict[str, Any] = {
        "brand": brand_name,
        "brandEn": brand_en,
        "model": model,
        "modelEn": _clean(row.get("modelEnglishName")),
        "trim": _clean(row.get("carTypeName")),
        "year": _to_int(row.get("carYear")),
        "price": _to_int(row.get("marketPrice")),  # تومان، بدون تبدیل
        "externalModelId": _clean(row.get("carModelId")),
        "externalTypeId": _clean(row.get("carTypeId")),
        "priceDate": _clean(brand.get("lastUpdateTime")),
        "url": _brand_url(page_url, brand_en),
    }
    return {k: v for k, v in item.items() if v is not None}


def parse_items(next_data: Dict[str, Any], page_url: str = DEFAULT_URL) -> List[Dict[str, Any]]:
    page_props = ((next_data or {}).get("props") or {}).get("pageProps") or {}
    brands = page_props.get("brandPricesList")
    if not isinstance(brands, list):
        raise NextDataNotFoundError("props.pageProps.brandPricesList در __NEXT_DATA__ نیست")
    items: List[Dict[str, Any]] = []
    for brand in brands:
        for row in (brand or {}).get("carPriceOnBrandDetails") or []:
            item = map_row(row or {}, brand, page_url)
            if item:
                items.append(item)
    return items


def batches(items: List[Dict[str, Any]], size: int = ITEMS_BATCH_MAX) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _ssl_context() -> ssl.SSLContext:
    import certifi

    ctx = ssl.create_default_context(cafile=certifi.where())
    if os.path.exists(EXTRA_CA_FILE):
        ctx.load_verify_locations(EXTRA_CA_FILE)
    return ctx


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT}, verify=_ssl_context()
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def fetch_html_playwright(url: str) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=USER_AGENT)
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            return await page.content()
        finally:
            await browser.close()


async def fetch_items(url: str) -> List[Dict[str, Any]]:
    """اول HTTP ساده؛ اگر __NEXT_DATA__ نبود یا درخواست شکست خورد ⇒ Playwright."""
    try:
        return parse_items(extract_next_data(await fetch_html(url)), url)
    except (httpx.HTTPError, NextDataNotFoundError) as e:
        print(f"[~] دریافت HTTP ساده ناموفق بود، fallback به Playwright: {e}")
    return parse_items(extract_next_data(await fetch_html_playwright(url)), url)


async def run_new_car_prices_job(run_id: str, url: str = DEFAULT_URL, client=None) -> Optional[int]:
    """fetch ⇒ ارسال batchها ⇒ end. خروجی: تعداد ردیف‌ها در صورت موفقیت، وگرنه None."""
    if client is None:
        from cars_api_client import CarsApiClient
        client = CarsApiClient()
    try:
        items = await fetch_items(url)
        if not items:
            raise RuntimeError("هیچ ردیف قیمتی از صفحه استخراج نشد")
        print(f"[+] new-car-prices run={run_id}: {len(items)} ردیف استخراج شد")
        for i, batch in enumerate(batches(items), 1):
            counts = await client.send_new_car_prices(run_id, batch)
            print(f"[+] new-car-prices run={run_id} batch {i}: {counts}")
        await client.end_new_car_prices_run(run_id, status="completed", total=len(items))
        return len(items)
    except RunNotRunningError as e:
        print(f"[~] ران new-car-prices {run_id} در بک‌اند دیگر در حال اجرا نیست؛ متوقف شد: {e}")
    except Exception as e:
        print(f"[✕] کرال new-car-prices run={run_id} با خطا متوقف شد: {e}")
        try:
            await client.end_new_car_prices_run(run_id, status="failed", error=(str(e) or type(e).__name__)[:2000])
        except RunNotRunningError:
            print(f"[~] run {run_id} قبلاً تمام/timeout شده بود")
        except Exception as end_err:
            print(f"[✕] پایان‌دادن به run {run_id} با خطا مواجه شد: {end_err}")
    return None


async def main_cli(url: str = DEFAULT_URL, dry_run: bool = False) -> int:
    if dry_run:
        items = await fetch_items(url)
        print(f"[+] {len(items)} ردیف (dry-run، چیزی ارسال نشد)")
        print(json.dumps(items[:3], ensure_ascii=False, indent=2))
        return 0 if items else 1
    from cars_api_client import CarsApiClient
    client = CarsApiClient()
    run_id = await client.start_new_car_prices_run(DEFAULT_SOURCE)
    print(f"[+] run شروع شد: {run_id}")
    total = await run_new_car_prices_job(run_id, url, client)
    return 0 if total else 1


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(os.environ.get("ENV_FILE", ".env"))
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    sys.exit(asyncio.run(main_cli(args[0] if args else DEFAULT_URL, dry_run="--dry-run" in sys.argv)))
