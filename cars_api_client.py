import asyncio
import os
import httpx
from typing import Any, Dict, Optional

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

    async def start_run(self, target_id: str, source: str, brand: str, car_model: str, trim: str) -> str:
        payload = {
            "targetId": target_id,
            "source": source,
            "brand": brand,
            "carModel": car_model,
            "trim": trim,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/crawl/runs/start", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data["_id"]

    async def send_listing(self, run_id: str, listing: Dict[str, Any], max_retries: int = 3, backoff_seconds: float = 2.0) -> None:
        """
        ارسال یک آگهی. در صورت 432 (رد قطعی، مثلاً اقساطی/قسطی/چکی) هیچ retry انجام نمی‌شود
        و آگهی نادیده گرفته می‌شود. در صورت 400 یا 5xx تا max_retries بار با backoff تلاش می‌شود.
        """
        payload = {"runId": run_id, **listing}
        for attempt in range(1, max_retries + 1):
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{self.base_url}/crawl/listings", json=payload, headers=self._headers())

            if resp.status_code == FINAL_REJECT_STATUS:
                print(f"[~] آگهی قطعاً رد شد (432): {listing.get('source_url')}")
                return

            if resp.status_code == 400 or resp.status_code >= 500:
                if attempt >= max_retries:
                    print(f"[✕] ارسال آگهی بعد از {attempt} تلاش ناموفق ماند (status={resp.status_code}): {listing.get('source_url')}")
                    return
                await asyncio.sleep(backoff_seconds * attempt)
                continue

            resp.raise_for_status()
            return

    async def end_run(self, run_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/crawl/runs/{run_id}/end", headers=self._headers())
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
