"""Daylight saving: the changeover days, a summer and a winter day, and a zone
that has no daylight saving at all (America/Phoenix).

The camera day is worked out from the sun, and frames are filed by local
clock time. Both must stay right when the clock jumps.
"""

import support  # noqa: F401  (must come first)

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import daylight
import frames

ANCHORAGE = ZoneInfo('America/Anchorage')
PHOENIX = ZoneInfo('America/Phoenix')
STG = dict(lat=56.5978, lon=-169.5464, tz=ANCHORAGE)
PHX = dict(lat=33.4484, lon=-112.0740, tz=PHOENIX)

# 2026: clocks go forward on 8 March, back on 1 November (US rules).
SPRING, FALL = date(2026, 3, 8), date(2026, 11, 1)


def hours(start, end):
    """Real elapsed hours, measured in UTC so a clock change cannot bend it."""
    return (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 3600


class TestLabels(unittest.TestCase):

    def test_summer_and_winter_carry_their_own_label(self):
        summer = daylight.window(date(2026, 7, 15), mode='civil', margin_min=0, **STG)
        winter = daylight.window(date(2026, 1, 15), mode='civil', margin_min=0, **STG)
        self.assertEqual({t.strftime('%Z') for t in summer}, {'AKDT'})
        self.assertEqual({t.strftime('%Z') for t in winter}, {'AKST'})

    def test_changeover_days_are_labelled_on_the_right_side(self):
        # Both changes happen at 2 AM, before civil dawn, so the whole
        # daylight window is already on the new clock.
        spring = daylight.window(SPRING, mode='civil', margin_min=0, **STG)
        fall = daylight.window(FALL, mode='civil', margin_min=0, **STG)
        self.assertEqual({t.strftime('%Z') for t in spring}, {'AKDT'})
        self.assertEqual({t.strftime('%Z') for t in fall}, {'AKST'})


class TestChangeoverDays(unittest.TestCase):
    """On a changeover day the daylight lasts about as long as on the days
    either side: the sun does not care about the clock. Its clock times move
    by an hour."""

    def check(self, day):
        before = daylight.window(day - timedelta(days=1), mode='civil', margin_min=0, **STG)
        on = daylight.window(day, mode='civil', margin_min=0, **STG)
        after = daylight.window(day + timedelta(days=1), mode='civil', margin_min=0, **STG)
        self.assertEqual(on[0].date(), day)
        for a, b in ((before, on), (on, after)):
            # Day length changes by a few minutes a day at this latitude,
            # never by anything near an hour.
            self.assertLess(abs(hours(*a) - hours(*b)), 0.25, (a, b))
        return before, on

    def test_spring_forward(self):
        before, on = self.check(SPRING)
        # Dawn on the clock jumps about an hour LATER (it is the same sun).
        shift = (on[0].hour * 60 + on[0].minute) - (before[0].hour * 60 + before[0].minute)
        self.assertTrue(50 <= shift <= 65, shift)

    def test_fall_back(self):
        before, on = self.check(FALL)
        shift = (on[0].hour * 60 + on[0].minute) - (before[0].hour * 60 + before[0].minute)
        self.assertTrue(-70 <= shift <= -50, shift)


class TestNoDaylightSaving(unittest.TestCase):

    def test_phoenix_keeps_one_offset_all_year(self):
        for day in (date(2026, 1, 15), SPRING, date(2026, 7, 15), FALL):
            start, end = daylight.window(day, mode='civil', margin_min=0, **PHX)
            self.assertEqual(start.utcoffset(), timedelta(hours=-7), day)
            self.assertEqual(start.strftime('%Z'), 'MST')
            self.assertEqual(start.date(), day)
            self.assertTrue(10 <= hours(start, end) <= 15.5, (day, hours(start, end)))

    def test_phoenix_changeover_days_do_not_jump(self):
        for day in (SPRING, FALL):
            a = daylight.window(day - timedelta(days=1), mode='civil', margin_min=0, **PHX)[0]
            b = daylight.window(day, mode='civil', margin_min=0, **PHX)[0]
            shift = (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
            self.assertTrue(-5 <= shift <= 5, (day, shift))


class TestFramesAcrossTheJump(unittest.TestCase):
    """Frames are filed by local clock time. Across spring forward there is
    no 2 AM folder; frames either side must still come back in order, and a
    stretch measured in real time must find them all."""

    def test_spring_forward_keeps_every_frame_in_order(self):
        root = tempfile.mkdtemp(prefix='webcam_dst_')
        first = datetime(2026, 3, 8, 1, 59, 45, tzinfo=ANCHORAGE)   # AKST
        # Real 15-second steps, expressed back on the local clock.
        taken = [(first.astimezone(timezone.utc) + timedelta(seconds=15 * i)).astimezone(ANCHORAGE)
                 for i in range(4)]
        self.assertEqual(taken[1].strftime('%H:%M:%S %Z'), '03:00:00 AKDT')
        for when in taken:
            support.touch_frame(root, when)
        found = frames.frames_between(root, taken[0] - timedelta(minutes=1),
                                      taken[-1] + timedelta(minutes=1), tz=ANCHORAGE)
        self.assertEqual([os.path.basename(p) for p in found],
                         [f'image_{t:%Y%m%d_%H%M%S}.jpg' for t in taken])
        self.assertFalse(os.path.isdir(os.path.join(root, '2026', '03', '08', '02')))

    def test_frame_name_reads_back_to_the_right_instant(self):
        when = datetime(2026, 7, 4, 12, 0, 0, tzinfo=ANCHORAGE)
        back = frames.frame_time(os.path.basename(frames.frame_path('/x', when)), ANCHORAGE)
        self.assertEqual(back.astimezone(timezone.utc), when.astimezone(timezone.utc))
        self.assertEqual(back.strftime('%Z'), 'AKDT')


if __name__ == '__main__':
    unittest.main()
