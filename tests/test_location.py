import json
import os
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from divar_location import extract_location, location_from_html, location_from_post_json  # noqa: E402


def extract(html, post_json=None):
    return extract_location(BeautifulSoup(html, "html.parser"), post_json)


class LocationTest(unittest.TestCase):
    def test_embedded_state_preloaded_city_object(self):
        # شکل واقعی window.__PRELOADED_STATE__ روی صفحه‌ی آگهی (ترتیب کلیدها همیشه همین نیست)
        state = json.dumps({"post": {"city": {"id": "1", "slug": "tehran", "parent": "904", "name": "تهران"}}}, ensure_ascii=False)
        html = f"<html><body><h1>پژو 207</h1><script>window.__PRELOADED_STATE__ = {state};</script></body></html>"
        self.assertEqual(
            extract(html),
            {"city_divar_id": "1", "province_divar_id": "904", "city_name": "تهران"},
        )

    def test_embedded_state_key_order_independent(self):
        html = """<script>window.x = {"city":{"name":"مشهد","parent":"13","id":"26","slug":"mashhad"}};</script>"""
        self.assertEqual(
            extract(html),
            {"city_divar_id": "26", "province_divar_id": "13", "city_name": "مشهد"},
        )

    def test_no_city_object_returns_empty(self):
        self.assertEqual(extract("<html><body><h1>بی‌عنوان</h1></body></html>"), {})

    def test_city_without_parent_still_returns_id_and_name(self):
        html = """<script>window.x = {"city":{"id":"1","name":"تهران"}};</script>"""
        self.assertEqual(location_from_html(BeautifulSoup(html, "html.parser")), {"city_divar_id": "1", "city_name": "تهران"})

    def test_post_api_json_shape(self):
        # شکل واقعی پاسخ api.divar.ir/v8/posts-v2/web/<token>: کلید city در ریشه
        api = {"city": {"city_id": "1", "name": "تهران", "parent_id": "904", "second_slug": "tehran"}, "sections": []}
        self.assertEqual(
            location_from_post_json(api),
            {"city_divar_id": "1", "province_divar_id": "904", "city_name": "تهران"},
        )

    def test_post_api_json_ignores_unrelated_city_id_scalars(self):
        # city_id خام در فیلترهای دیگر JSON نباید به‌عنوان شیء مکان گرفته شود
        api = {"sections": [{"widgets": [{"data": {"action": {"payload": {"filter": {"city_id": 1}}}}}]}]}
        self.assertEqual(location_from_post_json(api), {})

    def test_html_wins_over_post_json_when_both_present(self):
        html = """<script>window.x = {"city":{"id":"1","name":"تهران"}};</script>"""
        api = {"city": {"city_id": "99", "name": "مشهد", "parent_id": "13"}}
        self.assertEqual(
            extract(html, api),
            {"city_divar_id": "1", "city_name": "تهران"},
        )

    def test_falls_back_to_post_json_when_html_has_no_city(self):
        api = {"city": {"city_id": "1", "name": "تهران", "parent_id": "904"}}
        self.assertEqual(
            extract("<html><body><h1>بدون city</h1></body></html>", api),
            {"city_divar_id": "1", "province_divar_id": "904", "city_name": "تهران"},
        )

    def test_empty_post_json_returns_empty(self):
        self.assertEqual(location_from_post_json({}), {})
        self.assertEqual(location_from_post_json(None), {})


if __name__ == "__main__":
    unittest.main()
