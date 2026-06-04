"""Tests for the schedule parser."""

import pytest
from enrich.parser import parse_time, parse_schedule_rows, Event


class TestParseTime:
    def test_standard_range(self):
        start, end = parse_time("09:00-17:00")
        assert start == "09:00"
        assert end == "17:00"

    def test_range_with_spaces(self):
        start, end = parse_time("09:00 - 17:00")
        assert start == "09:00"
        assert end == "17:00"

    def test_range_no_colon_end(self):
        start, end = parse_time("09:00 - 1800")
        assert start == "09:00"
        assert end == "18:00"

    def test_all_week(self):
        start, end = parse_time("All week")
        assert start == "all_day"
        assert end == ""

    def test_all_day(self):
        start, end = parse_time("All day")
        assert start == "all_day"
        assert end == ""

    def test_coming_soon(self):
        start, end = parse_time("Coming soon")
        assert start == ""
        assert end == ""

    def test_tbc(self):
        start, end = parse_time("TBC")
        assert start == ""
        assert end == ""

    def test_en_dash(self):
        start, end = parse_time("10:00\u201312:00")
        assert start == "10:00"
        assert end == "12:00"

    def test_em_dash(self):
        start, end = parse_time("10:00\u201412:00")
        assert start == "10:00"
        assert end == "12:00"

    def test_empty(self):
        start, end = parse_time("")
        assert start == ""
        assert end == ""


class TestParseScheduleRows:
    def test_day_extraction(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Beach Party", "Acme Corp", "10:00-12:00", "Beach", "HERE", "Fun"],
            ["MONDAY 22ND", "", "", "", "", ""],
            ["Panel Talk", "BigCo", "14:00-15:00", "Stage", "HERE", "Talk"],
        ]
        events = parse_schedule_rows(rows, {})
        assert len(events) == 2
        assert events[0].day == "sunday"
        assert events[0].date == "2026-06-21"
        assert events[0].event_name == "Beach Party"
        assert events[1].day == "monday"
        assert events[1].date == "2026-06-22"

    def test_time_parsing_in_events(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Party", "Host", "09:00-17:00", "Loc", "", ""],
        ]
        events = parse_schedule_rows(rows, {})
        assert events[0].start_time == "09:00"
        assert events[0].end_time == "17:00"

    def test_status_derivation(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Event A", "Host", "Coming soon", "TBC", "", ""],
            ["Event B", "Host", "10:00-11:00", "Beach", "", ""],
        ]
        events = parse_schedule_rows(rows, {})
        assert events[0].status == "coming_soon"
        assert events[1].status == "confirmed"

    def test_hyperlink_injection_simple(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Event A", "Host", "10:00-11:00", "Beach", "HERE", ""],
        ]
        hyperlinks = {2: "https://example.com/event"}
        events = parse_schedule_rows(rows, hyperlinks)
        assert events[0].event_url == "https://example.com/event"

    def test_hyperlink_alignment_after_mega_row_split(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["Venue A\nVenue B", "Host A\nHost B", "All week\nAll week", "Loc A\nLoc B", "HERE\nHERE", ""],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Panel Talk", "BigCo", "14:00-15:00", "Stage", "HERE", ""],
        ]
        hyperlinks = {1: "https://venuea.com", 3: "https://panel.com"}
        events = parse_schedule_rows(rows, hyperlinks)
        venue_a = [e for e in events if e.event_name == "Venue A"]
        assert len(venue_a) == 1
        assert venue_a[0].event_url == "https://venuea.com"
        panel = [e for e in events if e.event_name == "Panel Talk"]
        assert len(panel) == 1
        assert panel[0].event_url == "https://panel.com"

    def test_mega_row_mismatched_columns_warns(self, capsys):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["A\nB\nC", "H1\nH2", "All week\nAll week\nAll week", "L1\nL2\nL3", "", ""],
        ]
        events = parse_schedule_rows(rows, {})
        captured = capsys.readouterr()
        assert "Warning" in captured.out or "warning" in captured.out
        assert len(events) == 3
        assert events[2].host == ""
