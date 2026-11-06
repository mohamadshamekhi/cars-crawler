source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8000

## قیمت خودروی صفر (همراه‌مکانیک)
- تریگر از cars-api: `POST /crawl/new-car-prices` با هدر `x-api-key` و بدنه‌ی `{"runId","source":"hamrah-mechanic","url"}` ⇒ 202؛ کار در پس‌زمینه (مستقل از صف کرال دیوار).
- داده از `__NEXT_DATA__` صفحه‌ی `https://www.hamrah-mechanic.com/carprice/` (HTTP ساده؛ Playwright فقط fallback) ⇒ batchهای ≤۵۰۰ به `/crawl/new-car-prices/runs/{runId}/items` ⇒ `/end`.
- اجرای دستی (start ⇒ crawl ⇒ end روی `CARS_API_BASE_URL`): `python new_car_prices.py`
- فقط تست parse بدون ارسال: `python new_car_prices.py --dry-run`

## تست
python -m unittest discover -s tests
