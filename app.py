"""Website xem Apple Calendar trên trình duyệt Kindle.

Trang được render hoàn toàn phía server (không cần JavaScript), chữ to,
đen trắng, độ tương phản cao để phù hợp màn hình e-ink.
"""

from __future__ import annotations

import calendar as pycal
import hmac
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from flask import Flask, abort, render_template, request

from calendar_source import CalendarSource, Event

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Đọc file .env đơn giản (không cần thư viện ngoài)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


def _env_list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Ho_Chi_Minh"))
LANGUAGE = os.environ.get("LANGUAGE", "vi").lower()
AGENDA_DAYS = max(1, _env_int("AGENDA_DAYS", 7))
REFRESH_SECONDS = max(0, _env_int("REFRESH_SECONDS", 300))
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
DEMO = os.environ.get("DEMO", "0").lower() in ("1", "true", "yes")

source = CalendarSource(
    tz=TZ,
    ics_urls=_env_list("ICS_URLS"),
    icloud_username=os.environ.get("ICLOUD_USERNAME", ""),
    icloud_password=os.environ.get("ICLOUD_APP_PASSWORD", ""),
    icloud_calendars=_env_list("ICLOUD_CALENDARS"),
    cache_seconds=max(0, _env_int("CACHE_MINUTES", 10)) * 60,
    demo_file=(BASE_DIR / "tests" / "sample.ics") if DEMO else None,
)

# ---------------- Ngôn ngữ ----------------
TEXT = {
    "vi": {
        "weekdays": ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"],
        "weekdays_short": ["T2", "T3", "T4", "T5", "T6", "T7", "CN"],
        "month": "Tháng",
        "today": "Hôm nay",
        "tomorrow": "Ngày mai",
        "upcoming": "Sắp tới",
        "day": "Ngày",
        "week": "Tuần",
        "month_view": "Tháng",
        "all_day": "Cả ngày",
        "no_events": "Không có sự kiện",
        "updated": "Cập nhật lúc",
        "prev": "« Trước",
        "next": "Sau »",
        "not_configured": "Chưa cấu hình nguồn lịch. Hãy đặt ICS_URLS hoặc ICLOUD_USERNAME/ICLOUD_APP_PASSWORD trong file .env (xem README).",
        "more": "khác",
        "refresh": "Tải lại",
    },
    "en": {
        "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "weekdays_short": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "month": "Month",
        "today": "Today",
        "tomorrow": "Tomorrow",
        "upcoming": "Upcoming",
        "day": "Day",
        "week": "Week",
        "month_view": "Month",
        "all_day": "All day",
        "no_events": "No events",
        "updated": "Updated at",
        "prev": "« Prev",
        "next": "Next »",
        "not_configured": "No calendar source configured. Set ICS_URLS or ICLOUD_USERNAME/ICLOUD_APP_PASSWORD in .env (see README).",
        "more": "more",
        "refresh": "Refresh",
    },
}
T = TEXT.get(LANGUAGE, TEXT["vi"])

app = Flask(__name__)


# ---------------- Bảo mật đơn giản ----------------
@app.before_request
def _check_token():
    if not ACCESS_TOKEN or request.path == "/healthz":
        return None
    supplied = request.args.get("key") or request.cookies.get("key") or ""
    if not hmac.compare_digest(supplied, ACCESS_TOKEN):
        abort(403)
    return None


@app.after_request
def _remember_token(resp):
    if ACCESS_TOKEN and request.args.get("key") == ACCESS_TOKEN:
        resp.set_cookie("key", ACCESS_TOKEN, max_age=3600 * 24 * 365, httponly=True, samesite="Lax")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def link(path: str, **params) -> str:
    """Tạo link, giữ ?key= để Kindle không cần cookie."""
    if ACCESS_TOKEN:
        params["key"] = ACCESS_TOKEN
    params = {k: v for k, v in params.items() if v is not None}
    return path + ("?" + urlencode(params) if params else "")


app.jinja_env.globals.update(link=link, T=T)


# ---------------- Helpers ----------------
def today() -> date:
    return datetime.now(TZ).date()


def parse_date(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return today()


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    nxt = d + timedelta(days=1)
    return start, datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ)


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def event_time_label(ev: Event, d: date) -> str:
    """Nhãn giờ của sự kiện khi hiển thị trong ngày d."""
    if ev.all_day:
        return T["all_day"]
    day_start, day_end = day_bounds(d)
    starts_today = ev.start >= day_start
    ends_today = ev.end <= day_end
    if starts_today and ends_today:
        if ev.end > ev.start:
            return f"{fmt_time(ev.start)}–{fmt_time(ev.end)}"
        return fmt_time(ev.start)
    if starts_today:
        return f"{fmt_time(ev.start)} →"
    if ends_today:
        return f"→ {fmt_time(ev.end)}"
    return T["all_day"]


def day_label(d: date) -> str:
    wd = T["weekdays"][d.weekday()]
    t = today()
    if LANGUAGE == "en":
        base = f"{wd}, {d.strftime('%b')} {d.day}"
    else:
        base = f"{wd}, {d.day}/{d.month}"
    if d == t:
        return f"{T['today']} · {base}"
    if d == t + timedelta(days=1):
        return f"{T['tomorrow']} · {base}"
    return base


def build_days(start: date, num_days: int):
    range_start, _ = day_bounds(start)
    _, range_end = day_bounds(start + timedelta(days=num_days - 1))
    result = source.get_events(range_start, range_end)
    days = []
    for i in range(num_days):
        d = start + timedelta(days=i)
        ds, de = day_bounds(d)
        items = [
            {"ev": ev, "time": event_time_label(ev, d)}
            for ev in result.events
            if ev.overlaps(ds, de)
        ]
        # sự kiện cả ngày (hoặc kéo dài nhiều ngày) lên đầu
        items.sort(key=lambda x: (x["time"] != T["all_day"], x["ev"].start, x["ev"].title.lower()))
        days.append({"date": d, "label": day_label(d), "is_today": d == today(), "events": items})
    return days, result


def common_context(result, view: str):
    now = datetime.now(TZ)
    show_calendar_name = len({ev.calendar for ev in result.events if ev.calendar}) > 1
    return {
        "now": now,
        "updated": fmt_time(now),
        "refresh": REFRESH_SECONDS,
        "errors": result.errors,
        "configured": source.configured,
        "view": view,
        "show_calendar_name": show_calendar_name,
        "today_iso": today().isoformat(),
    }


# ---------------- Routes ----------------
@app.route("/")
def upcoming():
    start = parse_date(request.args.get("date"))
    days, result = build_days(start, AGENDA_DAYS)
    return render_template(
        "agenda.html",
        title=T["upcoming"],
        heading=T["upcoming"],
        days=days,
        hide_empty=True,
        prev_url=link("/", date=(start - timedelta(days=AGENDA_DAYS)).isoformat()),
        next_url=link("/", date=(start + timedelta(days=AGENDA_DAYS)).isoformat()),
        **common_context(result, "upcoming"),
    )


@app.route("/day")
def day_view():
    d = parse_date(request.args.get("date"))
    days, result = build_days(d, 1)
    return render_template(
        "agenda.html",
        title=day_label(d),
        heading=day_label(d),
        days=days,
        hide_empty=False,
        single_day=True,
        prev_url=link("/day", date=(d - timedelta(days=1)).isoformat()),
        next_url=link("/day", date=(d + timedelta(days=1)).isoformat()),
        **common_context(result, "day"),
    )


@app.route("/week")
def week_view():
    d = parse_date(request.args.get("date"))
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    days, result = build_days(monday, 7)
    heading = f"{T['week']} {monday.day}/{monday.month} – {sunday.day}/{sunday.month}/{sunday.year}"
    return render_template(
        "agenda.html",
        title=heading,
        heading=heading,
        days=days,
        hide_empty=False,
        prev_url=link("/week", date=(monday - timedelta(days=7)).isoformat()),
        next_url=link("/week", date=(monday + timedelta(days=7)).isoformat()),
        **common_context(result, "week"),
    )


@app.route("/month")
def month_view():
    d = parse_date(request.args.get("date"))
    first = d.replace(day=1)
    grid_start = first - timedelta(days=first.weekday())
    last_day = pycal.monthrange(first.year, first.month)[1]
    last = first.replace(day=last_day)
    grid_end = last + timedelta(days=6 - last.weekday())
    num_days = (grid_end - grid_start).days + 1
    days, result = build_days(grid_start, num_days)
    for day in days:
        day["in_month"] = day["date"].month == first.month
    weeks = [days[i:i + 7] for i in range(0, len(days), 7)]

    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (last + timedelta(days=1))
    heading = f"{T['month']} {first.month}/{first.year}" if LANGUAGE != "en" else first.strftime("%B %Y")
    return render_template(
        "month.html",
        title=heading,
        heading=heading,
        weeks=weeks,
        max_per_day=_env_int("MONTH_MAX_EVENTS", 3),
        prev_url=link("/month", date=prev_month.isoformat()),
        next_url=link("/month", date=next_month.isoformat()),
        **common_context(result, "month"),
    )


@app.route("/healthz")
def healthz():
    return {"ok": True, "configured": source.configured}


if __name__ == "__main__":
    port = _env_int("PORT", 8000)
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
