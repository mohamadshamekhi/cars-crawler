import asyncio
from car_scraper import DivarCarScraper
from car_processor import DealScraperProcessor

async def main():
    print("=== مرحله ۱: شروع کرال آگهی‌ها ===")
    # مثال: برنده مدل ۲۰۷، سال ۱۴۰۰، بدنه سالم
    # URL ساخته‌شده: https://divar.ir/s/iran/car/peugeot/207i?production-year=1400-1400
    crawler_settings = {
        "headless": True,          # اگر می‌خواهی مرورگر نمایان باشد، بگذار False
        "delay_seconds": 1.5,
        "max_items": 5,            # تعداد آگهی‌های استخراجی
        # فیلترهای جستجو (از URLهای دیوار الگو گرفته شده‌اند):
        "country": "iran",         # "iran" (کل کشور) یا "tehran"
        "car_slug": "peugeot/207i",  # brand/slug   (حذف کن برای کل آگهی‌ها)
        "production_year": "1400-1400",  # سال ساخت (مثلا 1400-1400)
        "body_status": "intact",   # "intact" (سالم) یا "other" (سایر/ضربه‌خورد)
        # یا base_url دستی: "https://divar.ir/s/tehran/car"
        "base_url": None
    }
    
    scraper = DivarCarScraper(settings=crawler_settings)
    await scraper.run()

    print("\n=== مرحله ۲: شروع پردازش، فیلتر و امتیازدهی ===")
    dynamic_settings = {
        "banned_keywords": ["اقساط", "قسطی", "معاوضه", "چک", "لیزینگ", "پیش‌پرداخت", "حواله"],
        "filter_mode": "penalty",      # حالت: 'delete' (حذف کامل) یا 'penalty' (کسر امتیاز)
        "penalty_weight": 0.5,         # کسر ۵۰ درصد امتیاز در صورت وجود کلمات ممنوعه
        "alert_threshold": 40          # آستانه هشدار
    }
    
    processor = DealScraperProcessor(settings=dynamic_settings)
    processor.process_raw_data()

if __name__ == "__main__":
    asyncio.run(main())