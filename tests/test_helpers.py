"""Тесты handlers/helpers.py — парсинг длительности, форматирование."""

from handlers.helpers import escape_html_text, human_duration, parse_duration_and_reason


class TestParseDurationAndReason:
    def test_minutes_only(self):
        mins, reason = parse_duration_and_reason("30m")
        assert mins == 30
        assert reason == ""

    def test_hours(self):
        mins, reason = parse_duration_and_reason("2h")
        assert mins == 120

    def test_days(self):
        mins, reason = parse_duration_and_reason("7d")
        assert mins == 7 * 24 * 60

    def test_plain_number_is_minutes(self):
        mins, reason = parse_duration_and_reason("45")
        assert mins == 45

    def test_with_reason(self):
        mins, reason = parse_duration_and_reason("30m флуд в чате")
        assert mins == 30
        assert reason == "флуд в чате"

    def test_days_with_reason(self):
        mins, reason = parse_duration_and_reason("3d оскорбления")
        assert mins == 3 * 24 * 60
        assert reason == "оскорбления"

    def test_seconds_rounded_up_to_minute(self):
        mins, _ = parse_duration_and_reason("30s")
        assert mins == 1

    def test_seconds_over_minute(self):
        mins, _ = parse_duration_and_reason("90s")
        assert mins == 2

    def test_empty_string(self):
        mins, reason = parse_duration_and_reason("")
        assert mins == 0
        assert reason == ""

    def test_no_duration_returns_zero(self):
        mins, reason = parse_duration_and_reason("просто текст без длительности")
        assert mins == 0
        assert "текст" in reason

    def test_plain_number_with_reason(self):
        mins, reason = parse_duration_and_reason("60 спам")
        assert mins == 60
        assert reason == "спам"


class TestHumanDuration:
    def test_zero_is_forever(self):
        assert human_duration(0) == "навсегда"

    def test_negative_is_forever(self):
        assert human_duration(-1) == "навсегда"

    def test_minutes(self):
        assert human_duration(30) == "30 мин"

    def test_one_hour(self):
        assert human_duration(60) == "1ч"

    def test_hours_and_minutes(self):
        result = human_duration(90)
        assert "1ч" in result
        assert "30м" in result

    def test_one_day(self):
        assert human_duration(24 * 60) == "1д"

    def test_multiple_days(self):
        assert human_duration(7 * 24 * 60) == "7д"


class TestEscapeHtml:
    def test_escapes_angle_brackets(self):
        result = escape_html_text("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_escapes_ampersand(self):
        result = escape_html_text("a & b")
        assert "&amp;" in result

    def test_plain_text_unchanged(self):
        result = escape_html_text("обычный текст")
        assert result == "обычный текст"

    def test_empty_string(self):
        assert escape_html_text("") == ""
