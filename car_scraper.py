import asyncio
import json
import os
import re
from typing import Awaitable, Callable, Dict, Any, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError


SUGGESTION_CONTAINER_RE = re.compile(r'suggestions-row|keen-slider')


class DivarCarScraper:
    def __init__(self, settings: Dict[str, Any]):
        self.base_url = settings.get("base_url")
        self.headless = settings.get("headless", True)
        self.delay_seconds = settings.get("delay_seconds", 2.0)
        self.max_items = settings.get("max_items", 5)
        # فیلترهای URL: brand/model/slug, production-year (مثال: 1400-1400), body_status (intact یا other)
        self.body_status = settings.get("body_status", None)  # None | "intact" | "other"
        self.production_year = settings.get("production_year", None)  # None | "1400" | "1400-1400"
        self.car_slug = settings.get("car_slug", None)  # None | slug مثل peugeot/207i
        self.country = settings.get("country", "iran")  # iran یا tehran
        # پارامترهای generic اضافی که مستقیم به query string دیوار اضافه می‌شوند (کلید=نام پارامتر دیوار)
        self.extra_query_params: Dict[str, str] = settings.get("extra_query_params", {}) or {}
        # چند اسکرول پشت‌سرهم بدون لینک جدید = رسیدن به انتهای لیست
        self.max_stale_scrolls = settings.get("max_stale_scrolls", 3)
        # بعد از run: True فقط اگر کل لیست تا انتها اسکرول شد (نه سقف max_items) و همه‌ی آگهی‌ها بی‌خطا پردازش/ارسال شدند
        self.reached_end = False
        self.exhaustive = False

    async def _clean_number(self, text: Optional[str]) -> Optional[int]:
        """تبدیل دقیق اعداد فارسی/عربی به عدد صحیح"""
        if not text:
            return None
        persian_digits = '۰۱۲۳۴۵۶۷۸۹'
        arabic_digits = '٠١٢٣٤٥٦٧٨٩'
        for i in range(10):
            text = text.replace(persian_digits[i], str(i)).replace(arabic_digits[i], str(i))
        
        digits = re.sub(r'\D', '', text)
        return int(digits) if digits else None

    async def _extract_solar_year(self, text: Optional[str]) -> Optional[int]:
        """استخراج سال شمسی یا میلادی ۴ رقمی"""
        if not text:
            return None
        persian_digits = '۰۱۲۳۴۵۶۷۸۹'
        arabic_digits = '٠١٢٣٤٥٦٧٨٩'
        for i in range(10):
            text = text.replace(persian_digits[i], str(i)).replace(arabic_digits[i], str(i))
        
        match = re.search(r'\b(13\d{2}|14\d{2}|20\d{2})\b', text)
        if match:
            return int(match.group(1))
        return await self._clean_number(text)

    async def _build_base_url(self) -> str:
        """ساخت URL با فیلترهای کاربر: brand/model/slug، سال تولید، وضعیت بدنه"""
        country = (self.country or "iran").strip("/") or "iran"
        parts = [country, "car"]
        # بخش‌های خالی slug حذف می‌شوند تا هرگز // در URL نیاید (هدف «همه‌ی خودروها» = بدون slug)
        if self.car_slug:
            parts.extend(seg for seg in str(self.car_slug).split("/") if seg.strip())
        base = f"https://divar.ir/s/{'/'.join(parts)}"
        qs = []
        if self.production_year:
            qs.append(f"production-year={self.production_year}")
        if self.body_status:
            qs.append(f"body_status={self.body_status}%2C")
        for key, value in self.extra_query_params.items():
            if key == "production-year" and self.production_year:
                continue  # جلوگیری از پارامتر تکراری با self.production_year
            if key == "body_status" and self.body_status:
                continue  # جلوگیری از پارامتر تکراری با self.body_status
            qs.append(f"{key}={value}")
        if qs:
            base += "?" + "&".join(qs)
        return base

    async def fetch_card_links(self, page: Page) -> List[str]:
        if not self.base_url or not self.base_url.startswith("https://"):
            self.base_url = await self._build_base_url()
        print(f"[+] در حال بارگذاری صفحه آگهی‌ها با فیلترها: {self.base_url} (سقف: {self.max_items} آیتم)...")
        await page.goto(self.base_url, wait_until="domcontentloaded")
        await asyncio.sleep(self.delay_seconds)

        # اسکرول تا رسیدن به سقف max_items یا انتهای لیست (لیست دیوار ممکن است کارت‌های قبلی را از DOM حذف کند، پس تجمعی جمع می‌شود)
        links: List[str] = []
        self.reached_end = False
        stale = 0
        while len(links) < self.max_items:
            before = len(links)
            soup = BeautifulSoup(await page.content(), 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                # اسلایدر «آگهی‌های پیشنهادی در شهرهای اطراف» جزو نتایج جستجو نیست
                if '/v/' in href and not a_tag.find_parent(class_=SUGGESTION_CONTAINER_RE):
                    full_url = f"https://divar.ir{href}" if href.startswith('/') else href
                    if full_url not in links:
                        links.append(full_url)
                    if len(links) >= self.max_items:
                        break
            if len(links) >= self.max_items:
                break

            stale = stale + 1 if len(links) == before else 0
            if stale >= self.max_stale_scrolls:
                self.reached_end = True
                break

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            more = page.get_by_role("button", name=re.compile("آگهی‌های بیشتر|بیشتر"))
            if await more.count() and await more.first.is_visible():
                await more.first.click()
            await asyncio.sleep(self.delay_seconds)

        print(f"[✓] تعداد {len(links)} لینک آگهی استخراج شد{' (انتهای لیست)' if self.reached_end else ''}.")
        return links

    def _extract_image_urls(self, soup: BeautifulSoup, max_images: int = 20) -> List[str]:
        """لینک خام عکس‌های آگهی روی CDN دیوار؛ تصویر نقشه و تکراری‌های thumbnail حذف می‌شوند"""
        full_urls, thumb_urls, seen = [], [], set()
        for img in soup.find_all('img', class_=re.compile('kt-image-block__image')):
            src = img.get('src')
            if not src or 'mapimage.divarcdn.com' in src:
                continue
            filename = src.rsplit('/', 1)[-1]
            (thumb_urls if 'webp_thumbnail' in src else full_urls).append((filename, src))

        result = []
        for filename, src in full_urls + thumb_urls:
            if filename in seen:
                continue
            seen.add(filename)
            result.append(src)
            if len(result) >= max_images:
                break
        return result

    async def parse_car_details(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        try:
            print(f"[→] در حال کرال آگهی: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            
            # اسکرول به پایین صفحه برای رندر کامل عناصر
            await page.evaluate("window.scrollBy(0, 1200)")
            
            try:
                await page.wait_for_selector("p.kt-description-row__text", timeout=4000)
            except PlaywrightTimeoutError:
                pass

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            # ۱. عنوان آگهی
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "نامشخص"

            # ۲. موقعیت مکانی و زمان انتشار
            subtitle_info = ""
            if title_tag and title_tag.parent:
                sub_el = title_tag.parent.find_next_sibling('div')
                if sub_el:
                    subtitle_info = sub_el.get_text(strip=True)

            # ۳. استخراج دقیق برند، مدل و تریم از breadcrumb
            vehicle_info = {"brand": "", "model": "", "trim": ""}
            ignore_list = {
                "وسایل نقلیه", "خودرو", "خودرو سواری و وانت", "خودروی سواری", 
                "موتور سیکلت", "باربری", "سایر", "لوازم جانبی"
            }
            
            # گرفتن breadcrumb از لیست اصلی با کلاس kt-breadcrumbs
            breadcrumb_items = []
            breadcrumb_el = soup.find('ol', class_='kt-breadcrumbs')
            if breadcrumb_el:
                for li in breadcrumb_el.find_all('li', class_='kt-breadcrumbs__item'):
                    txt = li.get_text(strip=True)
                    if txt and txt not in ignore_list and 'معاوضه' not in txt:
                        if txt not in breadcrumb_items:
                            breadcrumb_items.append(txt)

            # fallback: اگر breadcrumb پیدا نشد
            if not breadcrumb_items:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '/s/' in href and '/car/' in href:
                        txt = a.get_text(strip=True)
                        if txt and txt not in ignore_list and len(txt) < 30 and 'معاوضه' not in txt:
                            if not any(char.isdigit() for char in txt[-4:]) or len(txt) > 15:
                                if txt not in breadcrumb_items:
                                    breadcrumb_items.append(txt)

            if len(breadcrumb_items) >= 1:
                vehicle_info["brand"] = breadcrumb_items[0]
            if len(breadcrumb_items) >= 2:
                vehicle_info["model"] = breadcrumb_items[1]
            if len(breadcrumb_items) >= 3:
                vehicle_info["trim"] = breadcrumb_items[2]

            # ۴. استخراج کارکرد، سال ساخت، رنگ و وضعیت بدنه از kt-group-row
            raw_km, raw_year, color, body_status = None, None, None, None
            group_table = soup.find('table', class_='kt-group-row')
            if group_table:
                headers = [th.get_text(strip=True) for th in group_table.find_all(['th', 'td'], class_=re.compile('heading|item'))]
                data_row = group_table.find('tr', class_='kt-group-row__data-row')
                if data_row:
                    cols = [td.get_text(strip=True) for td in data_row.find_all(['td', 'th'])]
                    for h, val in zip(headers, cols):
                        if 'کارکرد' in h:
                            raw_km = val
                        elif 'مدل' in h or 'سال' in h:
                            raw_year = val
                        elif 'رنگ' in h:
                            color = val
                        elif 'وضعیت بدنه' in h or 'دور دین' in h or 'بدنه' in h:
                            body_status = val

            # ۵. استخراج مشخصات از ردیف‌های kt-unexpandable-row
            raw_price = None
            insurance_term = None
            gearbox = None
            fuel_type = None

            unexp_rows = soup.find_all('div', class_=re.compile('kt-unexpandable-row'))
            for row in unexp_rows:
                title_el = row.find(class_=re.compile('kt-base-row__title'))
                val_el = row.find(class_=re.compile('kt-unexpandable-row__value-box'))
                if title_el and val_el:
                    key = title_el.get_text(strip=True)
                    val = val_el.get_text(strip=True)

                    if 'مهلت بیمه' in key:
                        insurance_term = val
                    elif key == 'گیربکس':
                        gearbox = val
                    elif 'نوع سوخت' in key:
                        fuel_type = val
                    elif 'قیمت' in key:
                        raw_price = val

            # ۶. استخراج ارزیابی فروشنده از kt-score-row
            seller_assessment = {}
            score_rows = soup.find_all('div', class_=re.compile('kt-score-row'))
            for row in score_rows:
                title_el = row.find(class_=re.compile('kt-score-row__title'))
                score_el = row.find(class_=re.compile('kt-score-row__score'))
                if title_el and score_el:
                    s_key = title_el.get_text(strip=True)
                    s_val = score_el.get_text(strip=True)
                    if 'موتور' in s_key:
                        seller_assessment['engine'] = s_val
                    elif 'شاسی' in s_key:
                        seller_assessment['chassis'] = s_val
                    elif 'بدنه' in s_key:
                        seller_assessment['body'] = s_val
                    elif 'گیربکس' in s_key:
                        seller_assessment['gearbox'] = s_val

            # ۷. استخراج لینک خام عکس‌ها از CDN دیوار (حداکثر ۲۰، بدون تکراری و بدون عکس نقشه)
            image_urls = self._extract_image_urls(soup)

            # ۸. استخراج دقیق توضیحات آگهی
            description = ""
            # پیدا کردن پاراگراف اصلی آگهی (نه تاریخ انتشار که در محتوای جمع‌شونده است)
            desc_p = None
            for p in soup.find_all('p', class_=re.compile('kt-description-row__text')):
                txt = p.get_text(strip=True)
                if txt and 'انتشار آگهی' not in txt and 'آخرین به‌روز‌رسانی' not in txt:
                    desc_p = p
                    break
            if desc_p:
                description = desc_p.get_text(separator="\n", strip=True)
            else:
                desc_row = soup.find('div', class_=re.compile('kt-description-row'))
                if desc_row:
                    description = desc_row.get_text(separator="\n", strip=True)
            # fallback: جمع‌آوری تمام متن‌های غیرتاریخ اگر هنوز خالی بود
            if not description.strip():
                candidates = []
                for p in soup.find_all('p', class_=re.compile('kt-description-row__text')):
                    txt = p.get_text(strip=True)
                    if txt and 'انتشار آگهی' not in txt and 'آخرین به‌روز‌رسانی' not in txt:
                        candidates.append(txt)
                if candidates:
                    description = "\n".join(candidates)

            # تمیزکاری اعداد
            price_numeric = await self._clean_number(raw_price) if raw_price else None
            year_numeric = await self._extract_solar_year(raw_year) if raw_year else None
            km_numeric = await self._clean_number(raw_km) if raw_km else None

            data = {
                "source_url": url,
                "title": title,
                "subtitle_info": subtitle_info,
                "vehicle_info": vehicle_info,
                "specifications": {
                    "raw_price": raw_price,
                    "price_numeric": price_numeric,
                    "year": year_numeric,
                    "mileage": km_numeric,
                    "color": color,
                    "body_status": body_status,
                    "insurance_term": insurance_term,
                    "gearbox": gearbox,
                    "fuel_type": fuel_type
                },
                "seller_assessment": seller_assessment,
                "description": description if description else "موردی برای نمایش وجود ندارد",
                "image_urls": image_urls,
                "crawled_at": asyncio.get_event_loop().time()
            }

            return data

        except Exception as e:
            print(f"[✕] خطایی در پردازش آگهی {url} رخ داد: {e}")
            return None

    async def run(self, on_item: Optional[Callable[[Dict[str, Any]], Awaitable[Optional[bool]]]] = None):
        """اجرای کرال. اگر on_item داده شود، به ازای هر آگهی موفق فوراً صدا زده می‌شود (مثلاً برای ارسال تکی به cars-api).
        on_item اگر False برگرداند یعنی آگهی ثبت نشد و run دیگر exhaustive حساب نمی‌شود."""
        self.exhaustive = False
        failures = 0
        async with async_playwright() as p:
            # داخل Docker: بدون sandbox (کاربر non-root بدون user namespace) و بدون اتکا به /dev/shm کوچک
            launch_kwargs: Dict[str, Any] = {
                "headless": self.headless,
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            }
            # داخل Docker از Chromium سیستم (apt) استفاده می‌شود؛ بدون این env همان مرورگر خود Playwright
            if os.environ.get("CHROMIUM_EXECUTABLE"):
                launch_kwargs["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
            browser = await p.chromium.launch(**launch_kwargs)
            try:
                context: BrowserContext = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={'width': 1280, 'height': 800}
                )
                page = await context.new_page()

                links = await self.fetch_card_links(page)

                scraped_data = []
                for link in links:
                    car_info = await self.parse_car_details(page, link)
                    if not car_info:
                        failures += 1
                        continue
                    scraped_data.append(car_info)
                    if on_item:
                        try:
                            if await on_item(car_info) is False:
                                failures += 1
                        except Exception as e:
                            failures += 1
                            print(f"[✕] خطا در ارسال/پردازش فوری آگهی {link}: {e}")
                self.exhaustive = self.reached_end and failures == 0
            finally:
                await browser.close()

            with open("cars_raw_data.json", "w", encoding="utf-8") as f:
                json.dump(scraped_data, f, ensure_ascii=False, indent=2)

            print(f"\n[★] کرال تمام شد. {len(scraped_data)} آگهی با موفقیت و اطلاعات بدون کلمات اضافی ذخیره شد.")
            return scraped_data