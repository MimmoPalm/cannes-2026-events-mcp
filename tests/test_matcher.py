"""Tests for the registration fuzzy matcher."""

from enrich.matcher import normalize_name, match_registrations
from enrich.parser import Event


class TestNormalizeName:
    def test_basic(self):
        assert normalize_name("  Microsoft  ") == "microsoft"

    def test_strip_at_cannes(self):
        assert normalize_name("Microsoft @ Cannes") == "microsoft"

    def test_strip_at_cannes_lowercase(self):
        assert normalize_name("google at cannes") == "google"

    def test_strip_at_cannes_lions(self):
        assert normalize_name("Meta at Cannes Lions") == "meta"


class TestMatchRegistrations:
    def test_exact_match(self):
        events = [
            Event(event_name="Party", host="Microsoft"),
            Event(event_name="Talk", host="Google"),
        ]
        registrations = [
            {"company": "Microsoft", "url": "https://ms.com/reg", "notes": "Free"},
        ]
        unmatched = match_registrations(events, registrations)
        assert events[0].registration_url == "https://ms.com/reg"
        assert events[0].registration_notes == "Free"
        assert events[1].registration_url == ""
        assert len(unmatched) == 0

    def test_fuzzy_match(self):
        events = [Event(event_name="Party", host="The Trade Desk")]
        registrations = [
            {"company": "Trade Desk @ Cannes", "url": "https://ttd.com", "notes": ""},
        ]
        unmatched = match_registrations(events, registrations)
        assert events[0].registration_url == "https://ttd.com"
        assert len(unmatched) == 0

    def test_one_reg_multiple_events(self):
        events = [
            Event(event_name="Talk 1", host="Microsoft"),
            Event(event_name="Talk 2", host="Microsoft"),
        ]
        registrations = [
            {"company": "Microsoft", "url": "https://ms.com/reg", "notes": ""},
        ]
        unmatched = match_registrations(events, registrations)
        assert events[0].registration_url == "https://ms.com/reg"
        assert events[1].registration_url == "https://ms.com/reg"

    def test_unmatched_returned(self):
        events = [Event(event_name="Party", host="Microsoft")]
        registrations = [
            {"company": "Obscure Corp XYZ", "url": "https://obscure.com", "notes": ""},
        ]
        unmatched = match_registrations(events, registrations)
        assert len(unmatched) == 1
        assert unmatched[0]["company"] == "Obscure Corp XYZ"
