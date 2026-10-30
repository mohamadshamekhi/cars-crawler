import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawl_incremental import (  # noqa: E402
    SEEN_BATCH_MAX,
    IncrementalTracker,
    chunk,
    normalize_price,
    token_from_url,
)


class PriceTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_price("۳,۰۵۰,۰۰۰,۰۰۰ تومان"), 3050000000)
        self.assertEqual(normalize_price("۳٬۰۵۰٬۰۰۰٬۰۰۰ تومان"), 3050000000)
        self.assertEqual(normalize_price("3,050,000,000"), 3050000000)
        self.assertEqual(normalize_price(3050000000), 3050000000)
        self.assertEqual(normalize_price(3050000000.0), 3050000000)

    def test_unreadable(self):
        for v in [None, "", "توافقی", "0 تومان", 0, True]:
            self.assertIsNone(normalize_price(v), v)

    def test_refresh_flag_reopens_a_known_listing(self):
        t = IncrementalTracker([{"token": "a", "price": 100, "refresh": True}, {"token": "b", "price": 100}])
        self.assertEqual(t.classify("a", "۱۰۰ تومان"), "changed")
        self.assertEqual(t.classify("b", "۱۰۰ تومان"), "unchanged")

    def test_classify(self):
        t = IncrementalTracker([{"token": "a", "price": 100}, {"token": "b", "price": None}])
        self.assertEqual(t.classify("a", "۱۰۰ تومان"), "unchanged")
        self.assertEqual(t.classify("a", "۱۲۰ تومان"), "changed")
        self.assertEqual(t.classify("a", None), "changed")  # قیمت کارت ناخوانا
        self.assertEqual(t.classify("a", "توافقی"), "changed")
        self.assertEqual(t.classify("b", "۱۰۰ تومان"), "changed")  # قیمت شناخته‌شده null
        self.assertEqual(t.classify("z", "۱۰۰ تومان"), "new")


class CounterTest(unittest.TestCase):
    def test_stop_after_k_consecutive(self):
        known = [{"token": f"k{i}", "price": 10} for i in range(10)]
        t = IncrementalTracker(known, stop_after_known=3)
        t.observe("k0", "10"); t.observe("k1", "10")
        self.assertFalse(t.should_stop)
        t.observe("new1", "10")  # جدید ⇒ ریست
        self.assertEqual(t.consecutive_known, 0)
        t.observe("k2", "11")  # تغییر قیمت ⇒ ریست
        self.assertEqual(t.consecutive_known, 0)
        t.observe("k3", "10"); t.observe("k4", "10")
        self.assertFalse(t.should_stop)
        t.observe("k5", "10")
        self.assertTrue(t.should_stop)
        self.assertEqual(t.stats, {"new": 1, "changed": 1, "unchanged": 5, "unknown": 0})

    def test_default_k(self):
        self.assertEqual(IncrementalTracker([], None).stop_after_known, 20)
        self.assertEqual(IncrementalTracker([], 0).stop_after_known, 20)


class SeenBatchTest(unittest.TestCase):
    def test_batches(self):
        n = SEEN_BATCH_MAX * 2 + 5
        t = IncrementalTracker([{"token": f"t{i}", "price": 1} for i in range(n)], stop_after_known=10 ** 6)
        for i in range(n):
            t.observe(f"t{i}", "1")
        self.assertEqual(len(t.take_seen_batch()), SEEN_BATCH_MAX)
        self.assertEqual(len(t.take_seen_batch()), SEEN_BATCH_MAX)
        self.assertEqual(t.take_seen_batch(), [])  # ۵ تای باقی‌مانده هنوز batch کامل نیست
        last = t.take_seen_batch(force=True)
        self.assertEqual(last, [f"t{i}" for i in range(n - 5, n)])
        self.assertEqual(t.take_seen_batch(force=True), [])

    def test_no_duplicates(self):
        t = IncrementalTracker([{"token": "a", "price": 1}])
        t.observe("a", "1"); t.observe("a", "1")
        self.assertEqual(t.take_seen_batch(force=True), ["a"])

    def test_chunk(self):
        self.assertEqual([len(c) for c in chunk(list(range(2500)))], [1000, 1000, 500])


class TokenTest(unittest.TestCase):
    def test_token(self):
        self.assertEqual(token_from_url("https://divar.ir/v/207-%D9%BE/gaf72dJB"), "gaf72dJB")
        self.assertEqual(token_from_url("/v/x/gaf72dJB/"), "gaf72dJB")
        self.assertEqual(token_from_url("https://divar.ir/v/x/gaf72dJB?a=1"), "gaf72dJB")


if __name__ == "__main__":
    unittest.main()
