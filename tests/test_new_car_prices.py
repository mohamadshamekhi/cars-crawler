import asyncio
import os
import sys
import unittest
from unittest import mock

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CARS_API_BASE_URL", "http://cars-api.test")
os.environ["CRAWLER_API_KEY"] = os.environ.get("CRAWLER_API_KEY") or "test-key"

import new_car_prices as ncp  # noqa: E402
from cars_api_client import CarsApiClient  # noqa: E402
from crawl_incremental import RunNotRunningError  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hamrah_carprice.html")
ALLOWED_FIELDS = {"brand", "brandEn", "model", "modelEn", "trim", "year", "price",
                  "externalModelId", "externalTypeId", "priceDate", "url"}
BASE = "http://cars-api.test"


def load_html():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def json_resp(status, body, method="POST", url=BASE):
    return httpx.Response(status, json=body, request=httpx.Request(method, url))


class ParseTest(unittest.TestCase):
    def test_extract_and_map(self):
        items = ncp.parse_items(ncp.extract_next_data(load_html()), ncp.DEFAULT_URL)
        self.assertEqual(len(items), 4)  # ردیف بی‌مدل حذف می‌شود
        self.assertEqual(items[0], {
            "brand": "آئودی", "brandEn": "audi", "model": "Q4 e-tron", "modelEn": "q4", "trim": "تیپ 40",
            "year": 2025, "price": 16000000000, "externalModelId": "713", "externalTypeId": "3013",
            "priceDate": "2026-11-06T09:33:32.6738661+03:30",
            "url": "https://www.hamrah-mechanic.com/carprice/audi/",
        })
        for it in items:
            self.assertTrue(set(it) <= ALLOWED_FIELDS, it)
            self.assertNotIn(None, it.values())

    def test_nulls_omitted(self):
        items = ncp.parse_items(ncp.extract_next_data(load_html()))
        sparse = items[-1]
        self.assertEqual(sparse["model"], "test model")
        self.assertEqual(set(sparse), {"brand", "model", "priceDate"})

    def test_missing_next_data(self):
        with self.assertRaises(ncp.NextDataNotFoundError):
            ncp.extract_next_data("<html></html>")
        with self.assertRaises(ncp.NextDataNotFoundError):
            ncp.parse_items({"props": {"pageProps": {}}})

    def test_brand_url_without_trailing_slash(self):
        self.assertEqual(ncp._brand_url("https://x.com/carprice", "Audi"), "https://x.com/carprice/audi/")
        self.assertIsNone(ncp._brand_url("https://x.com/carprice/", None))


class BatchTest(unittest.TestCase):
    def test_batches(self):
        items = [{"i": i} for i in range(1201)]
        sizes = [len(b) for b in ncp.batches(items)]
        self.assertEqual(sizes, [100] * 12 + [1])
        self.assertEqual(list(ncp.batches([])), [])


class FakeClient:
    def __init__(self, items_responses=None):
        self.sent = []
        self.ended = []
        self.items_responses = items_responses or []

    async def send_new_car_prices(self, run_id, batch):
        self.sent.append(len(batch))
        if self.items_responses:
            r = self.items_responses.pop(0)
            if isinstance(r, Exception):
                raise r
        return {"received": len(batch)}

    async def end_new_car_prices_run(self, run_id, status, total=None, error=None):
        self.ended.append({"status": status, "total": total, "error": error})


class JobTest(unittest.TestCase):
    def _run(self, client, items):
        with mock.patch.object(ncp, "fetch_items", mock.AsyncMock(return_value=items)):
            return asyncio.run(ncp.run_new_car_prices_job("r1", ncp.DEFAULT_URL, client))

    def test_completed(self):
        c = FakeClient()
        total = self._run(c, [{"brand": "b", "model": "m"}] * 1001)
        self.assertEqual(total, 1001)
        self.assertEqual(c.sent, [100] * 10 + [1])
        self.assertEqual(c.ended, [{"status": "completed", "total": 1001, "error": None}])

    def test_failed(self):
        c = FakeClient([RuntimeError("boom")])
        self.assertIsNone(self._run(c, [{"brand": "b", "model": "m"}]))
        self.assertEqual(c.ended, [{"status": "failed", "total": None, "error": "boom"}])

    def test_empty_is_failed(self):
        c = FakeClient()
        self.assertIsNone(self._run(c, []))
        self.assertEqual(c.ended[0]["status"], "failed")

    def test_run_not_running_stops_cleanly(self):
        c = FakeClient([{"ok": 1}, RunNotRunningError("gone")])
        self.assertIsNone(self._run(c, [{"brand": "b", "model": "m"}] * 1200))
        self.assertEqual(c.sent, [100, 100])  # batch سوم ارسال نمی‌شود
        self.assertEqual(c.ended, [])  # end صدا زده نمی‌شود


class ClientTest(unittest.TestCase):
    def _post(self, resp):
        return mock.patch("httpx.AsyncClient.post", mock.AsyncMock(return_value=resp))

    def test_send_items_ok(self):
        counts = {"received": 2, "created": 1, "changed": 0, "unchanged": 1, "skipped": 0,
                  "matched": 1, "partial": 0, "unmatched": 1, "errors": []}
        with self._post(json_resp(200, counts)) as post:
            out = asyncio.run(CarsApiClient(BASE, "k").send_new_car_prices("r1", [{"brand": "b"}]))
        self.assertEqual(out, counts)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{BASE}/crawl/new-car-prices/runs/r1/items")
        self.assertEqual(kwargs["json"], {"items": [{"brand": "b"}]})
        self.assertEqual(kwargs["headers"]["x-api-key"], "k")

    def test_send_items_run_not_running(self):
        with self._post(json_resp(409, {"code": "run_not_running"})):
            with self.assertRaises(RunNotRunningError):
                asyncio.run(CarsApiClient(BASE, "k").send_new_car_prices("r1", []))

    def test_other_409_is_http_error(self):
        with self._post(json_resp(409, {"code": "run_already_running"})):
            with self.assertRaises(httpx.HTTPStatusError):
                asyncio.run(CarsApiClient(BASE, "k").start_new_car_prices_run())

    def test_end_payloads(self):
        with self._post(json_resp(200, {})) as post:
            c = CarsApiClient(BASE, "k")
            asyncio.run(c.end_new_car_prices_run("r1", "completed", total=487))
            self.assertEqual(post.call_args.kwargs["json"], {"status": "completed", "total": 487})
            asyncio.run(c.end_new_car_prices_run("r1", "failed", error="x"))
            self.assertEqual(post.call_args.kwargs["json"], {"status": "failed", "error": "x"})
            self.assertEqual(post.call_args.args[0], f"{BASE}/crawl/new-car-prices/runs/r1/end")

    def test_start(self):
        with self._post(json_resp(201, {"runId": "abc"})) as post:
            self.assertEqual(asyncio.run(CarsApiClient(BASE, "k").start_new_car_prices_run()), "abc")
        self.assertEqual(post.call_args.kwargs["json"], {"source": "hamrah-mechanic"})


class FetchFallbackTest(unittest.TestCase):
    def test_playwright_fallback_when_no_next_data(self):
        with mock.patch.object(ncp, "fetch_html", mock.AsyncMock(return_value="<html></html>")), \
             mock.patch.object(ncp, "fetch_html_playwright", mock.AsyncMock(return_value=load_html())) as pw:
            items = asyncio.run(ncp.fetch_items(ncp.DEFAULT_URL))
        self.assertEqual(len(items), 4)
        pw.assert_awaited_once()


class EndpointTest(unittest.TestCase):
    def setUp(self):
        import app as app_module
        from fastapi.testclient import TestClient

        self.app_module = app_module
        self.client = TestClient(app_module.app)
        self.key = app_module.CRAWLER_API_KEY

    def test_accepts_and_schedules(self):
        with mock.patch.object(self.app_module, "run_new_car_prices_job", mock.AsyncMock()) as job:
            r = self.client.post("/crawl/new-car-prices", headers={"x-api-key": self.key},
                                 json={"runId": "r1", "source": "hamrah-mechanic", "url": ncp.DEFAULT_URL})
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json(), {"accepted": True, "runId": "r1"})
        job.assert_awaited_once_with("r1", ncp.DEFAULT_URL)

    def test_bad_key(self):
        r = self.client.post("/crawl/new-car-prices", headers={"x-api-key": "wrong"}, json={"runId": "r1"})
        self.assertEqual(r.status_code, 401)

    def test_foreign_url_rejected(self):
        r = self.client.post("/crawl/new-car-prices", headers={"x-api-key": self.key},
                             json={"runId": "r1", "url": "http://169.254.169.254/"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
