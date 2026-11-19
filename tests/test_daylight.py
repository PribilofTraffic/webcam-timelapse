"""The camera day: one stretch of light, named for the date it began."""

import support  # noqa: F401  (must come first)

import unittest
from datetime import date, datetime, timedelta

import daylight
import settings

TZ = settings.TZ


class TestWindow(unittest.TestCase):

    def test_june_runs_past_midnight(self):
        """The reason this module exists. St. George, 56.6 N on Alaska time:
        the June sun sets just after midnight and civil dusk is after 1 AM,
        so the video for the 20th ends on the 21st."""
        start, end = daylight.window(date(2026, 6, 20), mode='civil', margin_min=0)
        self.assertEqual(start.date(), date(2026, 6, 20))
        self.assertEqual(end.date(), date(2026, 6, 21))
        self.assertTrue(4 <= start.hour <= 6, start)
        self.assertTrue(1 <= end.hour <= 2, end)
        self.assertGreater(end - start, timedelta(hours=19))

    def test_june_sunset_itself_is_after_midnight(self):
        start, end = daylight.window(date(2026, 6, 20), mode='sun', margin_min=0)
        self.assertEqual(start.date(), date(2026, 6, 20))
        self.assertEqual(end.date(), date(2026, 6, 21))
        self.assertEqual(end.hour, 0)
        self.assertTrue(17 <= (end - start).total_seconds() / 3600 <= 18)

    def test_december_is_short_and_inside_one_date(self):
        start, end = daylight.window(date(2026, 12, 21), mode='civil', margin_min=0)
        self.assertEqual(start.date(), date(2026, 12, 21))
        self.assertEqual(end.date(), date(2026, 12, 21))
        self.assertTrue(8 <= (end - start).total_seconds() / 3600 <= 9.5)
        self.assertTrue(17 <= end.hour <= 19, end)

    def test_margin_widens_both_ends(self):
        plain = daylight.window(date(2026, 3, 20), mode='sun', margin_min=0)
        wide = daylight.window(date(2026, 3, 20), mode='sun', margin_min=60)
        self.assertEqual(plain[0] - wide[0], timedelta(hours=1))
        self.assertEqual(wide[1] - plain[1], timedelta(hours=1))

    def test_every_day_of_the_year_is_sane(self):
        """Starts on its own date, ends after it starts, is shorter than a
        day, and never runs into the next day's window."""
        for mode in ('civil', 'sun'):
            day = date(2026, 1, 1)
            previous_end = None
            while day <= date(2026, 12, 31):
                start, end = daylight.window(day, mode=mode, margin_min=0)
                self.assertEqual(start.date(), day, (mode, day))
                self.assertLess(start, end, (mode, day))
                self.assertLess(end - start, timedelta(hours=24), (mode, day))
                if previous_end is not None:
                    self.assertLessEqual(previous_end, start, (mode, day))
                previous_end = end
                day += timedelta(days=1)

    def test_midnight_sun_falls_back_to_the_calendar_day(self):
        """Above the Arctic Circle in June there is no dusk at all."""
        start, end = daylight.window(date(2026, 6, 20), mode='civil', margin_min=0,
                                     lat=71.29, lon=-156.79)
        self.assertEqual(start, datetime(2026, 6, 20, 0, 0, tzinfo=TZ))
        self.assertEqual(end, datetime(2026, 6, 21, 0, 0, tzinfo=TZ))

    def test_no_civil_dusk_falls_back_to_the_sun(self):
        """At 62 N in June the sun sets but never gets 6 degrees down."""
        start, end = daylight.window(date(2026, 6, 20), mode='civil', margin_min=0,
                                     lat=62.0, lon=-150.0)
        sun = daylight.window(date(2026, 6, 20), mode='sun', margin_min=60, lat=62.0, lon=-150.0)
        self.assertEqual(start, sun[0])
        self.assertLessEqual(end, sun[1])
        self.assertLess(end - start, timedelta(hours=24))


class TestClosedDays(unittest.TestCase):

    def test_winter_evening_today_is_done(self):
        now = datetime(2026, 12, 21, 21, 0, tzinfo=TZ)
        self.assertEqual(daylight.closed_days(now, 2),
                         [date(2026, 12, 19), date(2026, 12, 20), date(2026, 12, 21)])

    def test_winter_noon_today_is_not_done(self):
        now = datetime(2026, 12, 21, 12, 0, tzinfo=TZ)
        self.assertEqual(daylight.closed_days(now, 1), [date(2026, 12, 20)])

    def test_june_ten_pm_is_still_daylight(self):
        """The old fixed 10 PM render: the day is not over."""
        now = datetime(2026, 6, 20, 22, 0, tzinfo=TZ)
        self.assertNotIn(date(2026, 6, 20), daylight.closed_days(now, 1))

    def test_june_half_past_midnight_is_still_yesterday(self):
        now = datetime(2026, 6, 21, 0, 30, tzinfo=TZ)
        self.assertNotIn(date(2026, 6, 20), daylight.closed_days(now, 2))

    def test_june_three_am_yesterday_is_done(self):
        now = datetime(2026, 6, 21, 3, 0, tzinfo=TZ)
        days = daylight.closed_days(now, 2)
        self.assertIn(date(2026, 6, 20), days)
        self.assertNotIn(date(2026, 6, 21), days)


if __name__ == '__main__':
    unittest.main()
