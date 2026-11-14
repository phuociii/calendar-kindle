import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["DEMO"] = "1"
os.environ["ICS_URLS"] = ""

import icalendar  # noqa: E402

import app as webapp  # noqa: E402
from calendar_source import expand_calendar, normalize_url  # noqa: E402

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CAL = icalendar.Calendar.from_ical((Path(__file__).parent / "sample.ics").read_bytes())


def events_between(a, b):
    return expand_calendar(CAL, datetime(*a, tzinfo=TZ), datetime(*b, tzinfo=TZ), TZ)


def test_normalize_webcal():
    assert normalize_url("webcal://p01-caldav.icloud.com/x") == "https://p01-caldav.icloud.com/x"


def test_recurring_and_timezone():
    evs = events_between((2026, 11, 18), (2026, 11, 19))  # Thứ Tư
    titles = {e.title: e for e in evs}
    assert "Họp đứng hằng ngày" in titles
    utc = titles["Gọi video với team (giờ UTC)"]
    assert utc.start.hour == 14  # 07:00Z -> 14:00 +07


def test_cancelled_hidden_and_all_day():
    evs = events_between((2026, 11, 17), (2026, 11, 18))
    assert not any("huỷ" in e.title for e in evs)
    evs = events_between((2026, 11, 20), (2026, 11, 21))
    trip = [e for e in evs if e.title == "Du lịch Đà Lạt"][0]
    assert trip.all_day


def test_pages_render():
    client = webapp.app.test_client()
    for path in ["/", "/day?date=2026-11-14", "/week?date=2026-11-18", "/month?date=2026-11-01", "/month?date=bad"]:
        r = client.get(path)
        assert r.status_code == 200, path
    html = client.get("/week?date=2026-11-18").get_data(as_text=True)
    assert "Du lịch Đà Lạt" in html
    assert "Tập gym" in html
    day = client.get("/day?date=2026-11-15").get_data(as_text=True)
    assert "→ 01:30" in day  # sự kiện qua đêm


def test_token(monkeypatch):
    monkeypatch.setattr(webapp, "ACCESS_TOKEN", "secret")
    client = webapp.app.test_client()
    assert client.get("/").status_code == 403
    r = client.get("/?key=secret")
    assert r.status_code == 200
    assert "key=secret" in r.get_data(as_text=True)
    assert client.get("/").status_code == 200  # cookie đã được lưu
