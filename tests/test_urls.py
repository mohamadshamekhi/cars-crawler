import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _build_car_slug  # noqa: E402
from car_scraper import DivarCarScraper  # noqa: E402
from crawl_filters import apply_filters  # noqa: E402


def build_url(car_slug, filters=None, country="iran"):
    settings = {"country": country, "car_slug": car_slug}
    apply_filters(settings, filters)
    return asyncio.run(DivarCarScraper(settings)._build_base_url())


class CarSlugTest(unittest.TestCase):
    def test_no_brand(self):
        self.assertIsNone(_build_car_slug("", "", None))
        self.assertIsNone(_build_car_slug(None, None, None))
        self.assertIsNone(_build_car_slug("", "207i", None))

    def test_brand_only(self):
        self.assertEqual(_build_car_slug("peugeot", "", None), "peugeot")
        self.assertEqual(_build_car_slug("peugeot", None, "tu5"), "peugeot")

    def test_brand_model_trim(self):
        self.assertEqual(_build_car_slug("peugeot", "207i", None), "peugeot/207i")
        self.assertEqual(_build_car_slug("peugeot", "207i", "tu5"), "peugeot/207i-tu5")


class BaseUrlTest(unittest.TestCase):
    def test_all_cars(self):
        self.assertEqual(build_url(None), "https://divar.ir/s/iran/car")
        self.assertEqual(
            build_url(None, {"body_status": ["intact"]}, country="tehran"),
            "https://divar.ir/s/tehran/car?body_status=intact%2C",
        )

    def test_brand_only(self):
        self.assertEqual(build_url("peugeot"), "https://divar.ir/s/iran/car/peugeot")

    def test_brand_model(self):
        self.assertEqual(build_url("peugeot/207i"), "https://divar.ir/s/iran/car/peugeot/207i")

    def test_never_double_slash(self):
        for slug in ["", "/", "peugeot/", "/peugeot//207i/", "peugeot//"]:
            url = build_url(slug)
            self.assertNotIn("//", url.replace("https://", ""), slug)


if __name__ == "__main__":
    unittest.main()
