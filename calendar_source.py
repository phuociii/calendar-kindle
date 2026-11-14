"""Lấy và chuẩn hoá sự kiện từ Apple Calendar (iCloud).

Hỗ trợ 2 nguồn:
  * Link .ics / webcal:// (lịch công khai của iCloud hoặc bất kỳ lịch ICS nào)
  * iCloud CalDAV với Apple ID + mật khẩu ứng dụng (xem được lịch riêng tư)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

log = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"


@dataclass
class Event:
    title: str
    start: datetime  # luôn có timezone (giờ địa phương)
    end: datetime
    all_day: bool
    calendar: str = ""
    location: str = ""
    description: str = ""
    uid: str = ""

    def overlaps(self, day_start: datetime, day_end: datetime) -> bool:
        if self.end <= self.start:  # sự kiện không có thời lượng
            return day_start <= self.start < day_end
        return self.start < day_end and self.end > day_start


@dataclass
class FetchResult:
    events: list[Event] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched_at: datetime | None = None


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    return url


def _to_local(value, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Trả về (datetime có tz, all_day)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:  # giờ "floating" -> coi là giờ địa phương
            return value.replace(tzinfo=tz), False
        return value.astimezone(tz), False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=tz), True
    raise TypeError(f"Không hiểu kiểu ngày: {value!r}")


def _component_to_event(comp, tz: ZoneInfo, calendar_name: str) -> Event | None:
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return None
    dtstart = comp.get("DTSTART")
    if dtstart is None:
        return None
    start, all_day = _to_local(dtstart.dt, tz)

    dtend = comp.get("DTEND")
    if dtend is not None:
        end, _ = _to_local(dtend.dt, tz)
    elif comp.get("DURATION") is not None:
        end = start + comp.get("DURATION").dt
    else:
        end = start + (timedelta(days=1) if all_day else timedelta(0))

    return Event(
        title=str(comp.get("SUMMARY", "")).strip() or "(Không có tiêu đề)",
        start=start,
        end=end,
        all_day=all_day,
        calendar=calendar_name,
        location=str(comp.get("LOCATION", "")).strip(),
        description=str(comp.get("DESCRIPTION", "")).strip(),
        uid=str(comp.get("UID", "")),
    )


def expand_calendar(
    cal: icalendar.Calendar,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    calendar_name: str | None = None,
) -> list[Event]:
    name = calendar_name or str(cal.get("X-WR-CALNAME", "")).strip()
    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        if comp.name != "VEVENT":
            continue
        ev = _component_to_event(comp, tz, name)
        if ev is not None:
            events.append(ev)
    return events


class CalendarSource:
    """Lấy dữ liệu từ các nguồn đã cấu hình, có cache trong bộ nhớ."""

    def __init__(
        self,
        tz: ZoneInfo,
        ics_urls: list[str] | None = None,
        icloud_username: str = "",
        icloud_password: str = "",
        icloud_calendars: list[str] | None = None,
        cache_seconds: int = 600,
        demo_file: Path | None = None,
    ):
        self.tz = tz
        self.ics_urls = [normalize_url(u) for u in (ics_urls or []) if u.strip()]
        self.icloud_username = icloud_username
        self.icloud_password = icloud_password
        self.icloud_calendars = {c.strip().lower() for c in (icloud_calendars or []) if c.strip()}
        self.cache_seconds = cache_seconds
        self.demo_file = demo_file
        self._lock = threading.Lock()
        self._ics_cache: dict[str, tuple[float, icalendar.Calendar]] = {}
        self._caldav_cache: dict[tuple, tuple[float, list[tuple[str, icalendar.Calendar]]]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.ics_urls or self.demo_file or (self.icloud_username and self.icloud_password))

    # ---------- ICS ----------
    def _get_ics(self, url: str) -> icalendar.Calendar:
        now = time.time()
        cached = self._ics_cache.get(url)
        if cached and now - cached[0] < self.cache_seconds:
            return cached[1]
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "calendar-kindle/1.0"})
            resp.raise_for_status()
            cal = icalendar.Calendar.from_ical(resp.content)
        except Exception:
            if cached:  # dùng dữ liệu cũ nếu mạng lỗi
                log.warning("Lỗi tải %s, dùng cache cũ", url, exc_info=True)
                return cached[1]
            raise
        self._ics_cache[url] = (now, cal)
        return cal

    # ---------- CalDAV ----------
    def _get_caldav(self, start: datetime, end: datetime) -> list[tuple[str, icalendar.Calendar]]:
        # Làm tròn khoảng thời gian theo tháng để cache hiệu quả hơn
        win_start = (start - timedelta(days=start.day - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        win_end_base = end + timedelta(days=32)
        win_end = win_end_base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        key = (win_start, win_end)
        now = time.time()
        cached = self._caldav_cache.get(key)
        if cached and now - cached[0] < self.cache_seconds:
            return cached[1]

        import caldav  # import chậm, chỉ khi cần

        try:
            client = caldav.DAVClient(
                url=ICLOUD_CALDAV_URL,
                username=self.icloud_username,
                password=self.icloud_password,
            )
            principal = client.principal()
            result: list[tuple[str, icalendar.Calendar]] = []
            for cal in principal.calendars():
                name = _calendar_name(cal)
                if self.icloud_calendars and name.lower() not in self.icloud_calendars:
                    continue
                try:
                    objs = cal.search(start=win_start, end=win_end, event=True, expand=False)
                except Exception:
                    # Lịch "Nhắc nhở"/không hỗ trợ VEVENT có thể báo lỗi -> bỏ qua
                    log.info("Bỏ qua lịch %s", name, exc_info=True)
                    continue
                for obj in objs:
                    data = obj.data
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", "replace")
                    try:
                        result.append((name, icalendar.Calendar.from_ical(data)))
                    except Exception:
                        log.warning("Không đọc được sự kiện trong lịch %s", name, exc_info=True)
        except Exception:
            if cached:
                log.warning("Lỗi CalDAV, dùng cache cũ", exc_info=True)
                return cached[1]
            raise

        # giữ cache nhỏ gọn
        if len(self._caldav_cache) > 12:
            self._caldav_cache.clear()
        self._caldav_cache[key] = (now, result)
        return result

    # ---------- API chính ----------
    def get_events(self, start: datetime, end: datetime) -> FetchResult:
        res = FetchResult(fetched_at=datetime.now(self.tz))
        with self._lock:
            if self.demo_file:
                cal = icalendar.Calendar.from_ical(self.demo_file.read_bytes())
                res.events += expand_calendar(cal, start, end, self.tz)

            for url in self.ics_urls:
                try:
                    res.events += expand_calendar(self._get_ics(url), start, end, self.tz)
                except Exception as exc:
                    log.exception("Lỗi tải lịch ICS")
                    res.errors.append(f"Không tải được lịch ICS ({_short(url)}): {exc}")

            if self.icloud_username and self.icloud_password:
                try:
                    for name, cal in self._get_caldav(start, end):
                        res.events += expand_calendar(cal, start, end, self.tz, calendar_name=name)
                except Exception as exc:
                    log.exception("Lỗi CalDAV")
                    res.errors.append(f"Không kết nối được iCloud CalDAV: {exc}")

        # bỏ trùng (cùng UID + giờ bắt đầu) và sắp xếp
        seen = set()
        unique = []
        for ev in res.events:
            k = (ev.uid, ev.start, ev.title)
            if k in seen:
                continue
            seen.add(k)
            unique.append(ev)
        unique.sort(key=lambda e: (not e.all_day, e.start, e.title.lower()))
        res.events = unique
        return res


def _calendar_name(cal) -> str:
    for attr in ("get_display_name",):
        fn = getattr(cal, attr, None)
        if callable(fn):
            try:
                n = fn()
                if n:
                    return str(n)
            except Exception:
                pass
    return str(getattr(cal, "name", "") or "")


def _short(url: str) -> str:
    return url if len(url) <= 50 else url[:30] + "…" + url[-12:]
