from datetime import UTC, datetime

from usage_floor import humanize

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC).timestamp()


def test_relative_future_and_past():
    assert humanize.relative(30) == "now"
    assert humanize.relative(4 * 60) == "in 4 min"
    assert humanize.relative(3 * 3600 + 12 * 60) == "in 3 h 12 min"
    assert humanize.relative(2 * 3600) == "in 2 h"
    assert humanize.relative(26 * 3600) == "in 1 day 2 h"
    assert humanize.relative(5 * 86400 + 3600) == "in 5 days"
    assert humanize.relative(-2 * 60) == "2 min ago"


def test_date_label_uses_day_month_short_year():
    label = humanize.date_label(datetime(2026, 11, 24, 14, 0, tzinfo=UTC))
    assert label.startswith(("24 Nov '26", "23 Nov '26", "25 Nov '26"))  # local time zone may shift the day
    assert ", " in label


def test_when_combines_date_and_relative():
    text = humanize.when("2026-11-23T12:00:00+00:00", now=NOW)
    assert text.endswith("(in 5 days)")
    assert "Nov '26" in text


def test_unknown_values():
    assert humanize.when(None) == "-"
    assert humanize.when("not a date") == "-"
    assert humanize.ago(None) == "never"
