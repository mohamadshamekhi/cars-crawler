import asyncio
import os
import httpx
from typing import Any, Dict, List, Optional

from crawl_incremental import RunNotRunningError

# کد رد قطعی آگهی اقساطی/مشکوک توسط cars-api؛ نهایی است، نباید retry شود
FINAL_REJECT_STATUS = 432
RETRYABLE_STATUSES_MIN = 400  # 400 و همه 5xx قابل retry هستند (432 از این قاعده مستثنی است)

CARS_API_BASE_URL = os.environ.get("CARS_API_BASE_URL", "").rstrip("/")
CRAWLER_API_KEY = os.environ.get("CRAWLER_API_KEY", "")


class CarsApiClient:
    """کلاینت ارتباط با cars-api برای ثبت start/listings/end یک اجرای کرال"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or CARS_API_BASE_URL).rstrip("/")
        self.api_key = api_key or CRAWLER_API_KEY
        if not self.base_url:
            raise RuntimeError("CARS_API_BASE_URL تنظیم نشده است")

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def _raise_if_run_not_running(resp: httpx.Response) -> None:
        """409 با code=run_not_running ⇒ ران تمام/timeout شده؛ کرال باید تمیز متوقف شود"""
        if resp.status_code != 409:
            return
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("code") == "run_not_running":
            raise RunNotRunningError(body.get("message") or "run_not_running")

    async def start_run(self, target_id: str, source: str, brand: str, car_model: str, trim: str, mode: Optional[str] = None) -> str:
        payload = {
            "targetId": target_id,
            "source": source,
            "brand": brand,
            "carModel": car_model,
            "trim": trim,
        }
        # خالی ⇒ بک‌اند خودش mode را تعیین می‌کند
        if mode:
            payload["mode"] = mode
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/crawl/runs/start", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data["_id"]

    async def send_listing(self, run_id: str, listing: Dict[str, Any], max_retries: int = 3, backoff_seconds: float = 2.0) -> bool:
        """
        ارسال یک آگهی. در صورت 432 (رد قطعی، مثلاً اقساطی/قسطی/چکی) هیچ retry انجام نمی‌شود
        و آگهی نادیده گرفته می‌شود. در صورت 400 یا 5xx تا max_retries بار با backoff تلاش می‌شود.
        خروجی: True اگر آگهی ثبت یا قطعاً رد (432) شد؛ False اگر بعد از همه‌ی تلاش‌ها ناموفق ماند.
        """
        payload = {"runId": run_id, **listing}
        for attempt in range(1, max_retries + 1):
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{self.base_url}/crawl/listings", json=payload, headers=self._headers())

            self._raise_if_run_not_running(resp)
            if resp.status_code == FINAL_REJECT_STATUS:
                print(f"[~] آگهی قطعاً رد شد (432): {listing.get('source_url')}")
                return True

            if resp.status_code == 400 or resp.status_code >= 500:
                if attempt >= max_retries:
                    print(f"[✕] ارسال آگهی بعد از {attempt} تلاش ناموفق ماند (status={resp.status_code}): {listing.get('source_url')}")
                    return False
                await asyncio.sleep(backoff_seconds * attempt)
                continue

            resp.raise_for_status()
            return True
        return False

    async def end_run(self, run_id: str, exhaustive: bool = False, stopped_early: bool = False) -> None:
        """exhaustive=True فقط وقتی کل لیست تا انتها کرال و بی‌خطا ارسال شد؛ بک‌اند بر اساس آن آگهی‌های غایب را removed می‌کند.
        stopped_early=True یعنی ران incremental بعد از K آگهی شناخته‌شده‌ی بدون تغییر متوقف شد."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/crawl/runs/{run_id}/end",
                json={"exhaustive": exhaustive, "stoppedEarly": stopped_early},
                headers=self._headers(),
            )
            self._raise_if_run_not_running(resp)
            resp.raise_for_status()

    async def mark_filters_supported(self, source: str, keys: list) -> None:
        """اعلام به بک‌اند که این کلیدهای فیلتر توسط کرالر پشتیبانی می‌شوند (supported=true در crawl_source_filters)"""
        if not keys:
            return
        payload = {"source": source, "supportedKeys": keys}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/crawl/source-filters/supported", json=payload, headers=self._headers())
            resp.raise_for_status()

    async def get_divar_filters(self) -> list:
        """تعریف فیلترهای دیوار از بک‌اند (برای تشخیص نوع multi-select و امثال آن)"""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.base_url}/crawl-sources/divar/filters", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_known_listings(self, target_id: str, days: int = 14, limit: int = 5000) -> Dict[str, Any]:
        """آگهی‌های اخیر هدف برای ران incremental: {targetId, count, truncated, items:[{token, price, lastSeenAt}]}"""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{self.base_url}/crawl/targets/{target_id}/known-listings",
                params={"days": days, "limit": limit},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def mark_seen(self, run_id: str, tokens: List[str]) -> List[str]:
        """«هنوز هست» برای آگهی‌های بدون تغییر (≤۱۰۰۰ توکن)؛ خروجی: tokenهایی که بک‌اند نمی‌شناسد (باید کامل کرال شوند)"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/crawl/runs/{run_id}/seen", json={"tokens": tokens}, headers=self._headers())
        self._raise_if_run_not_running(resp)
        resp.raise_for_status()
        return list(resp.json().get("unknown") or [])
