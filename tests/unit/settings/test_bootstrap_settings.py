"""Tests for the optional MEMBERS_BOOTSTRAP_JSON config."""

import json

import pytest

from template.settings.bootstrap_settings import BootstrapSettings


class TestBootstrapSettings:
    def test_unset_env_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("MEMBERS_BOOTSTRAP_JSON", raising=False)
        assert BootstrapSettings().parse_members() == []

    def test_empty_string_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("MEMBERS_BOOTSTRAP_JSON", "")
        assert BootstrapSettings().parse_members() == []

    def test_parses_valid_json_array(self, monkeypatch):
        payload = [
            {"name": "Alice", "email": "alice@example.com", "telephone": "5491100000001"},
            {"name": "Bob", "email": "bob@example.com", "telephone": "5491100000002"},
        ]
        monkeypatch.setenv("MEMBERS_BOOTSTRAP_JSON", json.dumps(payload))

        members = BootstrapSettings().parse_members()

        assert len(members) == 2
        assert members[0].name == "Alice"
        assert members[0].email == "alice@example.com"
        assert members[1].telephone == "5491100000002"

    def test_invalid_json_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("MEMBERS_BOOTSTRAP_JSON", "{not valid json")
        assert BootstrapSettings().parse_members() == []

    def test_non_array_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("MEMBERS_BOOTSTRAP_JSON", json.dumps({"name": "Alice"}))
        assert BootstrapSettings().parse_members() == []

    def test_invalid_email_raises(self, monkeypatch):
        monkeypatch.setenv(
            "MEMBERS_BOOTSTRAP_JSON",
            json.dumps([{"name": "Alice", "email": "not-an-email", "telephone": "5491100000001"}]),
        )
        with pytest.raises(Exception):  # pydantic ValidationError
            BootstrapSettings().parse_members()
