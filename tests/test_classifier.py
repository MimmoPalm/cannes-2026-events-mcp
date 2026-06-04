"""Tests for the classifier validation logic."""

from enrich.classifier import validate_classification, COMPANY_TYPES, EVENT_TYPES


class TestValidateClassification:
    def test_valid_classification(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "party",
            "target_audience": "publishers, brands",
            "crawled_summary": "A great event.",
        })
        assert result["company_type"] == "adtech"
        assert result["event_type"] == "party"
        assert result["target_audience"] == "publishers, brands"

    def test_invalid_company_type_falls_back(self):
        result = validate_classification({
            "company_type": "startup",
            "event_type": "party",
            "target_audience": "everyone",
            "crawled_summary": "",
        })
        assert result["company_type"] == "other"

    def test_invalid_event_type_falls_back(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "gala_dinner",
            "target_audience": "everyone",
            "crawled_summary": "",
        })
        assert result["event_type"] == "other"

    def test_missing_fields_get_defaults(self):
        result = validate_classification({})
        assert result["company_type"] == "other"
        assert result["event_type"] == "other"
        assert result["target_audience"] == "everyone"
        assert result["crawled_summary"] == ""

    def test_invalid_audience_values_filtered(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "panel",
            "target_audience": "publishers, ceos, brands",
            "crawled_summary": "",
        })
        assert result["target_audience"] == "publishers, brands"

    def test_all_invalid_audience_falls_back_to_everyone(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "panel",
            "target_audience": "executives, vips",
            "crawled_summary": "",
        })
        assert result["target_audience"] == "everyone"
