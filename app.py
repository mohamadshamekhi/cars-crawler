import asyncio
import os
from dotenv import load_dotenv

# برای تست با یک cars-api موقت/mock: ENV_FILE=.env.test uvicorn app:app ...
# بدون تعیین ENV_FILE، همیشه همان .env واقعی پروژه لود می‌شود (دست‌نخورده)
load_dotenv(os.environ.get("ENV_FILE", ".env"))

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Any, Dict, Literal, Optional

from car_scraper import DivarCarScraper
from cars_api_client import CarsApiClient
from crawl_filters import apply_filters, FALLBACK_MULTI_SELECT_KEYS
from crawl_incremental import DEFAULT_STOP_AFTER_KNOWN, IncrementalTracker, RunNotRunningError

CRAWLER_API_KEY = os.environ.get("CRAWLER_API_KEY", "")
# سقف مرورگرهای همزمان (هر کرال یک Chromium)؛ بقیه‌ی درخواست‌ها در صف می‌مانند تا RAM سرور پر نشود
MAX_CONCURRENT_CRAWLS = max(1, int(os.environ.get("MAX_CONCURRENT_CRAWLS", "2")))
_crawl_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

app = FastAPI(title="Divar Car Crawler")


class CrawlRequest(BaseModel):
    targetId: str
    source: str
    brand: Optional[str] = None
    carModel: Optional[str] = None
    trim: Optional[str] = None
    carSlug: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    # incremental: فقط آگهی‌های جدید/تغییرقیمت‌داده باز می‌شوند؛ خالی ⇒ full (و بک‌اند خودش mode را تعیین می‌کند)
    mode: Optional[Literal["full", "incremental"]] = None
    stopAfterKnown: Optional[int] = DEFAULT_STOP_AFTER_KNOWN


def _verify_api_key(x_api_key: Optional[str]):
    if not CRAWLER_API_KEY or x_api_key != CRAWLER_API_KEY:
        raise HTTPException(status_code=401, detail="کلید API نامعتبر است")


def _build_car_slug(brand: Optional[str], car_model: Optional[str], trim: Optional[str]) -> Optional[str]:
    """None برای «همه‌ی خودروها»، فقط brand اگر مدل خالی است، وگرنه brand/model[-trim]"""
    brand = (brand or "").strip().strip("/")
    car_model = (car_model or "").strip().strip("/")
    if not brand:
        return None
    if not car_model:
        return brand
    model_part = f"{car_model}-{trim.strip()}" if trim and trim.strip() else car_model
    return f"{brand}/{model_part}"


def _is_multi_select(filter_def: Dict[str, Any]) -> bool:
    t = str(filter_def.get("type", "")).lower()
    if "multi" in t:
        return True
    return bool(filter_def.get("multiple") or filter_def.get("isMultiple"))


async def _get_multi_select_keys(client: CarsApiClient) -> set:
    """نوع فیلترهای دیوار را از GET /crawl-sources/divar/filters می‌گیرد؛ در صورت خطا به لیست fallback برمی‌گردد"""
    try:
        filter_defs = await client.get_divar_filters()
        keys = set()
        for f in filter_defs:
            key = f.get("key") or f.get("slug") or f.get("name")
            if key and _is_multi_select(f):
                keys.add(key)
        return keys or FALLBACK_MULTI_SELECT_KEYS
    except Exception as e:
        print(f"[~] گرفتن تعریف فیلترهای دیوار ناموفق بود، از fallback استفاده شد: {e}")
        return FALLBACK_MULTI_SELECT_KEYS


async def _run_crawl_job(payload: CrawlRequest):
    async with _crawl_semaphore:
        await _run_crawl_job_unlocked(payload)


async def _run_crawl_job_unlocked(payload: CrawlRequest):
    client = CarsApiClient()
    run_id = None
    exhaustive = False
    stopped_early = False
    run_alive = True
    mode = payload.mode
    tracker = None
    try:
        if mode == "incremental":
            try:
                known = await client.get_known_listings(payload.targetId)
                tracker = IncrementalTracker(known.get("items") or [], payload.stopAfterKnown or DEFAULT_STOP_AFTER_KNOWN)
                print(f"[+] incremental: {known.get('count', len(tracker.known))} آگهی شناخته‌شده"
                      f"{' (truncated)' if known.get('truncated') else ''}، توقف بعد از {tracker.stop_after_known} بدون تغییر")
            except Exception as e:
                print(f"[~] گرفتن known-listings ناموفق بود، ران به‌صورت full اجرا می‌شود: {e}")
                mode = "full"

        run_id = await client.start_run(
            target_id=payload.targetId,
            source=payload.source,
            brand=payload.brand or "",
            car_model=payload.carModel or "",
            trim=payload.trim or "",
            mode=mode,
        )

        scraper_settings = {
            "headless": True,
            "delay_seconds": 1.5,
            "max_items": 20,
            "country": "iran",
            "car_slug": payload.carSlug or _build_car_slug(payload.brand, payload.carModel, payload.trim),
            "base_url": None,
        }
        multi_select_keys = await _get_multi_select_keys(client)
        _, supported_keys = apply_filters(scraper_settings, payload.filters, multi_select_keys)
        scraper = DivarCarScraper(settings=scraper_settings)

        if supported_keys:
            try:
                await client.mark_filters_supported(payload.source, supported_keys)
            except Exception as e:
                print(f"[~] اعلام کلیدهای پشتیبانی‌شده ({supported_keys}) به بک‌اند با خطا مواجه شد: {e}")

        async def on_item(listing: dict):
            vehicle_info = listing.get("vehicle_info") or {}
            if not vehicle_info.get("brand") or not vehicle_info.get("model"):
                print(f"[~] آگهی بدون brand/model شناخته‌شده نادیده گرفته شد: {listing.get('source_url')}")
                return True
            return await client.send_listing(run_id, listing)

        async def on_seen(tokens: list):
            return await client.mark_seen(run_id, tokens)

        await scraper.run(on_item=on_item, tracker=tracker, on_seen=on_seen)
        exhaustive = scraper.exhaustive
        stopped_early = scraper.stopped_early
    except RunNotRunningError as e:
        run_alive = False
        print(f"[~] ران targetId={payload.targetId} در بک‌اند دیگر در حال اجرا نیست؛ کرال متوقف شد: {e}")
    except Exception as e:
        print(f"[✕] اجرای کرال targetId={payload.targetId} با خطا متوقف شد: {e}")
    finally:
        if run_id and run_alive:
            try:
                await client.end_run(run_id, exhaustive=exhaustive, stopped_early=stopped_early)
            except RunNotRunningError:
                print(f"[~] run {run_id} قبلاً تمام/timeout شده بود")
            except Exception as e:
                print(f"[✕] پایان‌دادن به run {run_id} با خطا مواجه شد: {e}")


@app.post("/crawl", status_code=202)
async def crawl(payload: CrawlRequest, background_tasks: BackgroundTasks, x_api_key: Optional[str] = Header(default=None)):
    _verify_api_key(x_api_key)
    background_tasks.add_task(_run_crawl_job, payload)
    return {"accepted": True, "targetId": payload.targetId}
