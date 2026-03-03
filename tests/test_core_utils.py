"""Тесты web/utils.py и core/tz.py."""
import datetime

import pytest

from core.tz import to_msk, to_msk_str
from web.utils import parse_duration_to_minutes, to_unix_ts_utc


class TestParseDurationToMinutes:
    def test_minutes(self):
        assert parse_duration_to_minutes("30m") == 30

    def test_hours(self):
        assert parse_duration_to_minutes("2h") == 120

    def test_days(self):
        assert parse_duration_to_minutes("1d") == 1440

    def test_plain_number(self):
        assert parse_duration_to_minutes("45") == 45

    def test_empty_string(self):
        assert parse_duration_to_minutes("") == 0

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_duration_to_minutes("abc")

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError):
            parse_duration_to_minutes("10x")


class TestToUnixTsUtc:
    def test_naive_datetime_treated_as_utc(self):
        dt = datetime.datetime(2024, 1, 1, 12, 0, 0)
        ts = to_unix_ts_utc(dt)
        # 2024-01-01 12:00:00 UTC
        assert ts == int(datetime.datetime(2024, 1, 1, 12, 0, 0,
                                           tzinfo=datetime.timezone.utc).timestamp())

    def test_aware_datetime(self):
        dt = datetime.datetime(2024, 6, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)
        ts = to_unix_ts_utc(dt)
        assert isinstance(ts, int)
        assert ts > 0

    def test_none_returns_none(self):
        assert to_unix_ts_utc(None) is None


class TestTimezone:
    def test_to_msk_naive_datetime(self):
        dt = datetime.datetime(2024, 1, 1, 9, 0, 0)  # 09:00 UTC → 12:00 MSK
        result = to_msk(dt)
        assert result is not None
        assert result.hour == 12

    def test_to_msk_str_returns_string(self):
        dt = datetime.datetime(2024, 3, 15, 10, 30, 0)
        result = to_msk_str(dt)
        assert isinstance(result, str)
        assert "15.03.2024" in result

    def test_to_msk_str_none(self):
        assert to_msk_str(None) == "-"
