import json
from typing import Dict, Any, List


class DealScraperProcessor:
    def __init__(self, settings: Dict[str, Any]):
        """
        تنظیمات پویای سیستم (قابل تغییر از طریق پنل ادمین)
        """
        self.banned_keywords = settings.get("banned_keywords", ["اقساط", "قسطی", "معاوضه", "چک", "لیزینگ", "حواله"])
        self.filter_mode = settings.get("filter_mode", "penalty")  # گزینه‌ها: 'delete' (حذف کامل) یا 'penalty' (کسر امتیاز)
        self.penalty_weight = settings.get("penalty_weight", 0.4)  # میزان جریمه (مثلاً ۴۰ درصد کسر امتیاز)
        self.alert_threshold = settings.get("alert_threshold", 75)  # آستانه ارسال هشدار

    def _apply_text_filter(self, text: str) -> Dict[str, Any]:
        """اعمال فیلتر متنی پویا روی توضیحات و عنوان آگهی"""
        text_lower = text.lower()
        found_keywords = [kw for kw in self.banned_keywords if kw in text_lower]
        
        has_banned = len(found_keywords) > 0
        is_filtered = False
        score_multiplier = 1.0

        if has_banned:
            if self.filter_mode == 'delete':
                is_filtered = True  # آگهی باید کلاً حذف شود
            elif self.filter_mode == 'penalty':
                # اعمال جریمه امتیازی
                score_multiplier = (1.0 - self.penalty_weight)

        return {
            "has_banned_keywords": has_banned,
            "found_keywords": found_keywords,
            "is_filtered": is_filtered,
            "score_multiplier": score_multiplier
        }

    def _calculate_deal_score(self, car: Dict[str, Any], filter_result: Dict[str, Any]) -> int:
        """محاسبه امتیاز نهایی ارزش خرید (0 تا 100)"""
        if filter_result["is_filtered"]:
            return 0

        base_score = 80  # امتیاز اولیه فرضی بر اساس جذابیت قیمت
        final_score = int(base_score * filter_result["score_multiplier"])
        
        return max(0, min(100, final_score))

    def process_raw_data(self, input_filename: str = "cars_raw_data.json", output_filename: str = "cars_processed_data.json"):
        """پردازش لیست آگهی‌های خام کرال شده"""
        try:
            with open(input_filename, "r", encoding="utf-8") as f:
                raw_cars = json.load(f)
        except FileNotFoundError:
            print(f"[✕] فایل {input_filename} یافت نشد. لطفاً ابتدا کرالر را اجرا کنید.")
            return

        processed_cars = []

        print(f"\n[+] در حال پردازش {len(raw_cars)} آگهی و اعمال فیلترهای پویا...")
        
        for car in raw_cars:
            # ترکیب عنوان و توضیحات برای بررسی دقیق‌تر
            full_text = f"{car.get('title', '')} {car.get('description', '')}"

            # ۱. اجرای فیلتر متنی پویا
            filter_result = self._apply_text_filter(full_text)

            # ۲. محاسبه امتیاز ارزش خرید
            deal_score = self._calculate_deal_score(car, filter_result)

            # ۳. بررسی وضعیت ارسال هشدار (Alert Trigger)
            send_alert = deal_score >= self.alert_threshold and not filter_result["is_filtered"]

            # انتقال اطلاعات کامل شامل سال ساخت و کارکرد (اصلاح آدرس‌دهی بهSpecifications)
            spec = car.get("specifications", {})
            processed_item = {
                "source_url": car.get("source_url"),
                "title": car.get("title"),
                "raw_price": car.get("raw_price") or spec.get("raw_price"),
                "price_numeric": car.get("price_numeric") or spec.get("price_numeric"),
                "year": car.get("year") or spec.get("year"),
                "mileage": car.get("mileage") or spec.get("mileage"),
                "color": spec.get("color"),
                "body_status": spec.get("body_status"),
                "vehicle_info": car.get("vehicle_info", {}),
                "filter_details": filter_result,
                "deal_score": deal_score,
                "send_alert": send_alert
            }

            if not filter_result["is_filtered"] or self.filter_mode != 'delete':
                processed_cars.append(processed_item)

        # ذخیره خروجی پردازش شده
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(processed_cars, f, ensure_ascii=False, indent=2)

        print(f"[✓] پردازش کامل شد. {len(processed_cars)} آگهی معتبر در '{output_filename}' ذخیره شد.")
        
        # نمایش خلاصه نتایج در ترمینال
        for idx, item in enumerate(processed_cars, 1):
            alert_status = "🚨 [فرصت ویژه / ارسال هشدار]" if item["send_alert"] else "📌 [عادی]"
            print(f"\n{idx}. {item['title']}")
            print(f"   - سال ساخت: {item.get('year')} | کارکرد: {item.get('mileage')} کیلومتر")
            print(f"   - امتیاز ارزش خرید: {item['deal_score']} / 100  {alert_status}")
            if item['filter_details']['has_banned_keywords']:
                print(f"   - ⚠️ کلمات مشکوک یافت شده: {item['filter_details']['found_keywords']} (اعمال جریمه)")


# --- نحوه تست و اجرا ---
if __name__ == "__main__":
    dynamic_settings = {
        "banned_keywords": ["اقساط", "قسطی", "معاوضه", "چک", "لیزینگ", "پیش‌پرداخت", "حواله"],
        "filter_mode": "penalty",      # حالت: 'delete' (حذف کامل) یا 'penalty' (کسر امتیاز)
        "penalty_weight": 0.5,         # کسر ۵۰ درصد امتیاز در صورت وجود کلمات مشکوک
        "alert_threshold": 40          # آستانه هشدار
    }

    processor = DealScraperProcessor(settings=dynamic_settings)
    processor.process_raw_data()