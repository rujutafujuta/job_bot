"""Tests for form field learning module."""

import pytest
from unittest.mock import patch, mock_open
from src.pipeline.form_learner import lookup_field, prompt_and_learn, _get_nested


_PROFILE = {
    "personal": {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-1234",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "github_url": "https://github.com/janedoe",
        "portfolio_url": "https://janedoe.dev",
        "address": "San Francisco, CA",
    },
    "target": {
        "desired_salary": "150000",
        "willing_to_relocate": "no",
    },
    "visa": {
        "authorized_to_work": "yes",
        "status": "citizen",
        "requires_sponsorship": "no",
    },
    "employment": {
        "currently_employed": "yes",
        "notice_period_days": "14",
        "earliest_start_date": "2026-06-01",
    },
    "eeo": {
        "disability_status": "no",
        "veteran_status": "no",
        "race_ethnicity": "prefer not to say",
    },
    "learned_answers": {
        "background_check": "yes",
        "overtime": "yes",
    },
}


class TestGetNested:
    def test_simple_key(self):
        assert _get_nested({"a": "b"}, "a") == "b"

    def test_nested_key(self):
        assert _get_nested({"a": {"b": "c"}}, "a.b") == "c"

    def test_missing_key_returns_none(self):
        assert _get_nested({"a": "b"}, "c") is None

    def test_missing_nested_returns_none(self):
        assert _get_nested({"a": {}}, "a.b") is None

    def test_none_value_returns_none(self):
        assert _get_nested({"a": None}, "a") is None

    def test_non_dict_midpath_returns_none(self):
        assert _get_nested({"a": "string"}, "a.b") is None


class TestLookupField:
    def test_email_field(self):
        assert lookup_field("Email", _PROFILE) == "jane@example.com"

    def test_full_name_field(self):
        assert lookup_field("Full Name", _PROFILE) == "Jane Doe"

    def test_phone_field(self):
        assert lookup_field("Phone Number", _PROFILE) == "555-1234"

    def test_linkedin_field(self):
        assert lookup_field("LinkedIn Profile URL", _PROFILE) == "https://linkedin.com/in/janedoe"

    def test_salary_field(self):
        assert lookup_field("Desired Salary", _PROFILE) == "150000"

    def test_visa_field(self):
        assert lookup_field("Work Authorization", _PROFILE) == "citizen"

    def test_learned_answer(self):
        assert lookup_field("background check", _PROFILE) == "yes"

    def test_learned_answer_case(self):
        assert lookup_field("Background Check", _PROFILE) == "yes"

    def test_unknown_field_returns_none(self):
        assert lookup_field("Favorite Color", _PROFILE) is None

    def test_empty_label_returns_none(self):
        assert lookup_field("", _PROFILE) is None


class TestPromptAndLearn:
    def test_learnable_field_saved_to_profile(self, tmp_path):
        profile_yaml = tmp_path / "user_profile.yaml"
        profile_yaml.write_text("personal:\n  full_name: Jane Doe\n")
        profile = {"personal": {"full_name": "Jane Doe"}}

        with patch("builtins.input", return_value="yes"):
            result = prompt_and_learn("overtime", profile, profile_path=profile_yaml)

        assert result == "yes"
        assert profile.get("learned_answers", {}).get("overtime") == "yes"

    def test_non_learnable_field_not_saved(self, tmp_path):
        profile_yaml = tmp_path / "user_profile.yaml"
        profile_yaml.write_text("{}\n")
        profile = {}

        with patch("builtins.input", return_value="blue"):
            result = prompt_and_learn("Favorite Color", profile, profile_path=profile_yaml)

        assert result == "blue"
        assert "learned_answers" not in profile

    def test_empty_answer_not_saved(self, tmp_path):
        profile_yaml = tmp_path / "user_profile.yaml"
        profile_yaml.write_text("{}\n")
        profile = {}

        with patch("builtins.input", return_value=""):
            prompt_and_learn("overtime", profile, profile_path=profile_yaml)

        assert "learned_answers" not in profile
