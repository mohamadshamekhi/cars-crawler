import os
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from divar_description import extract_description  # noqa: E402


def extract(html):
    return extract_description(BeautifulSoup(html, "html.parser"))


DESCRIPTION = "مدل ۲۰۱۵\nبدونه رنگ\nفنی در حد صفر\nقابل معاوضه با خودرو قیمت پایین تر"


class DescriptionTest(unittest.TestCase):
    def test_classic_description_row_skips_dates(self):
        html = """
        <div class="kt-description-row">
          <p class="kt-description-row__text">انتشار آگهی: ۲ ساعت پیش</p>
          <p class="kt-description-row__text kt-description-row__text--primary">مدل ۲۰۱۵<br>بدونه رنگ<br>فنی در حد صفر<br>قابل معاوضه با خودرو قیمت پایین تر</p>
        </div>"""
        self.assertEqual(extract(html), DESCRIPTION)

    def test_new_markup_found_by_the_heading(self):
        # کلاس‌ها عوض شده‌اند؛ فقط عنوان «توضیحات» ثابت است
        html = """
        <section><h2 class="x1">ارزیابی فروشنده</h2><div class="r"><span>موتور</span><span>سالم</span></div></section>
        <section>
          <div class="title-x"><h2 class="x1">توضیحات</h2></div>
          <div class="desc-y"><p class="z">مدل ۲۰۱۵<br/>بدونه رنگ<br/>فنی در حد صفر<br/>قابل معاوضه با خودرو قیمت پایین تر</p></div>
          <div class="tags"><a href="/s/car">خودرو سواری و وانت</a></div>
        </section>"""
        self.assertEqual(extract(html), DESCRIPTION)

    def test_heading_without_text_does_not_grab_other_sections(self):
        html = """
        <div><h2>توضیحات</h2></div>
        <div><a href="/s/car">خودرو سواری و وانت</a></div>
        <div><h2>گزارش آگهی</h2><p>متن دیگر</p></div>"""
        self.assertEqual(extract(html), "")

    def test_json_ld_fallback(self):
        html = """<script type="application/ld+json">{"@type":"Car","name":"سمند","description":"بدون رنگ\\nبیمه تا آخر سال"}</script>"""
        self.assertEqual(extract(html), "بدون رنگ\nبیمه تا آخر سال")

    def test_meta_fallback_and_empty(self):
        self.assertEqual(
            extract('<meta property="og:description" content="یک لکه رنگ روی گلگیر">'),
            "یک لکه رنگ روی گلگیر",
        )
        self.assertEqual(extract("<div>هیچ</div>"), "")


if __name__ == "__main__":
    unittest.main()
