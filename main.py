import os
import re
import sqlite3
from datetime import date, timedelta
from collections import Counter
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

#========== TOKEN ===========
BOT_TOKEN = "8019460541:AAG8SdItiQBhdOxPsg2wzhfc9It3PD5B2fI"  #========== TOKEN ===========
DB_FILE = "lotobot.db"
REGION = "mn"
DRAW_LIMIT = 40

WEEKDAY_TO_STATIONS = {
    "Monday": ["TP. Hồ Chí Minh", "Đồng Tháp", "Cà Mau"],
    "Tuesday": ["Bến Tre", "Vũng Tàu", "Bạc Liêu"],
    "Wednesday": ["Đồng Nai", "Cần Thơ", "Sóc Trăng"],
    "Thursday": ["Tây Ninh", "An Giang", "Bình Thuận"],
    "Friday": ["Vĩnh Long", "Bình Dương", "Trà Vinh"],
    "Saturday": ["TP. Hồ Chí Minh", "Long An", "Bình Phước", "Hậu Giang"],
    "Sunday": ["Tiền Giang", "Kiên Giang", "Đà Lạt"],
}

WEEKDAY_VN = {
        "Monday": "Thứ Hai",
        "Tuesday": "Thứ Ba",
        "Wednesday": "Thứ Tư",
        "Thursday": "Thứ Năm",
        "Friday": "Thứ Sáu",
        "Saturday": "Thứ Bảy",
        "Sunday": "Chủ Nhật",
    }

URL_TMPL = "https://www.xosominhngoc.com/ket-qua-xo-so/mien-nam/{dmy}.html"

def init_db() -> None:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS results(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region TEXT NOT NULL,
                    date TEXT NOT NULL,
                    numbers TEXT NOT NULL,
                    UNIQUE(region, date)
                )
                """
            )

def fetch_mn(day: date) -> Tuple[str, str]:
        try:
            dmy = day.strftime("%d-%m-%Y")
            resp = requests.get(URL_TMPL.format(dmy=dmy), timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            nums = [
                td.get_text(strip=True)
                for td in soup.find_all("td")
                if re.fullmatch(r"\d{2,6}", td.get_text(strip=True))
            ]
            if not nums:
                raise ValueError(f"Không tìm thấy số cho {dmy}")
            return day.isoformat(), ",".join(nums)
        except requests.RequestException as e:
            raise ValueError(f"Lỗi khi lấy dữ liệu cho {dmy}: {str(e)}")

def save_result(region: str, draw_date: str, numbers: str) -> None:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO results(region, date, numbers) VALUES (?, ?, ?)",
                (region, draw_date, numbers),
            )

def recent_draws(region: str, limit_: int) -> List[Tuple[str, str]]:
        with sqlite3.connect(DB_FILE) as conn:
            return conn.execute(
                "SELECT date, numbers FROM results WHERE region = ? ORDER BY date DESC LIMIT ?",
                (region, limit_),
            ).fetchall()

def ensure_cache_today() -> None:
        draws = recent_draws(REGION, DRAW_LIMIT)
        if draws and draws[0][0] == date.today().isoformat() and len(draws) >= DRAW_LIMIT:
            return
        day = date.today()
        collected = {d for d, _ in draws}
        while len(collected) < DRAW_LIMIT:
            iso = day.isoformat()
            if iso not in collected:
                try:
                    d, nums = fetch_mn(day)
                    save_result(REGION, d, nums)
                    collected.add(iso)
                except Exception as e:
                    print(f"Lỗi khi lấy dữ liệu cho {iso}: {str(e)}")
            day -= timedelta(days=1)

def thong_ke_tan_suat(draws: List[Tuple[str, str]]) -> Counter:
        freq = Counter({f"{i:02d}": 0 for i in range(100)})
        for _, num_str in draws:
            for n in num_str.split(","):
                if n and len(n) >= 2:  # Đảm bảo số hợp lệ
                    freq[n[-2:]] += 1
        return freq

def goiy_so(freq: Counter):
        sorted_items = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        dan_so = [s for s, _ in sorted_items[:8]]
        xi2 = [
            (dan_so[i], dan_so[j])
            for i in range(len(dan_so))
            for j in range(i + 1, len(dan_so))
        ][:8]
        # Chỉ tạo xiên 3 nếu có đủ số
        xi3 = [dan_so[i:i+3] for i in range(0, len(dan_so)-2, 3) if len(dan_so[i:i+3]) == 3]
        return dan_so, xi2, xi3

def get_today_info():
        try:
            today = date.today()
            weekday_en = today.strftime("%A")
            thu_vn = WEEKDAY_VN.get(weekday_en, "Không xác định")
            stations = WEEKDAY_TO_STATIONS.get(weekday_en, [])
            if not stations:
                raise ValueError("Không tìm thấy thông tin đài cho ngày này")
            return weekday_en, thu_vn, stations
        except Exception as e:
            raise ValueError(f"Lỗi khi lấy thông tin ngày: {str(e)}")

def format_goiy_message() -> str:
        try:
            ensure_cache_today()
            draws = recent_draws(REGION, DRAW_LIMIT)
            if not draws:
                return "❌ Không có dữ liệu để thống kê"

            freq = thong_ke_tan_suat(draws)
            dan_so, xi2, xi3 = goiy_so(freq)
            _, thu_vn, stations = get_today_info()

            chi_tiet_lines = [
                f"{d}: {', '.join(dan_so[i::len(stations)])}"
                for i, d in enumerate(stations)
            ]

            xi2_text = "\n • " + "\n • ".join([f"{a} – {b}" for a, b in xi2]) if xi2 else "Không có"
            xi3_text = "\n • " + "\n • ".join([" – ".join(x) for x in xi3]) if xi3 else "Không có"

            return (
                f"🎯 SIÊU TRÍ TUỆ – MIỀN NAM\n"
                f"📅 HÔM NAY: {thu_vn}\n"
                f"🏟️ CÁC ĐÀI: {' | '.join(stations)}\n"
                f"📊 THỐNG KÊ {DRAW_LIMIT} kỳ gần nhất\n"
                "────────────────────────────\n"
                f"🧨 DÀN SỐ ĐỀ XUẤT:\n➡️ {', '.join(dan_so)}\n"
                f"📌 CHI TIẾT:\n • " + "\n • ".join(chi_tiet_lines) + "\n"
                "────────────────────────────\n"
                f"🤝 XIÊN 2 ({len(xi2)} cặp):{xi2_text}\n"
                "────────────────────────────\n"
                f"🎯 XIÊN 3 ({len(xi3)} bộ):{xi3_text}\n"
                "────────────────────────────\n"
                f"🤖 NHẬN XÉT:\n"
                f" • NÊN GIỮ: {dan_so[0] if dan_so else 'N/A'}, {dan_so[1] if len(dan_so) > 1 else 'N/A'}\n"
                f" • GHÉP TỐT: {dan_so[2] if len(dan_so) > 2 else 'N/A'}–{dan_so[3] if len(dan_so) > 3 else 'N/A'}, "
                f"{dan_so[4] if len(dan_so) > 4 else 'N/A'}–{dan_so[5] if len(dan_so) > 5 else 'N/A'}\n"
                f" • TREND 2-3 NGÀY: {dan_so[6] if len(dan_so) > 6 else 'N/A'}, {dan_so[7] if len(dan_so) > 7 else 'N/A'}"
            )
        except Exception as e:
            return f"❌ Lỗi khi tạo thống kê: {str(e)}"

async def mn(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            msg = format_goiy_message()
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")

def main():
        try:
            init_db()
            app = ApplicationBuilder().token(BOT_TOKEN).build()
            app.add_handler(CommandHandler("mn", mn))
            print("✅ Bot đang chạy – Gõ /mn để thống kê")
            app.run_polling()
        except Exception as e:
            print(f"❌ Lỗi khi khởi động bot: {str(e)}")

if __name__ == "__main__":
        main()
