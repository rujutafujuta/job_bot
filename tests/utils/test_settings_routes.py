"""Tests for /settings GET and POST routes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.web.app import app, _PROFILE_PATH, _ROLES_PATH


@pytest.fixture
def client(tmp_path, monkeypatch):
    profile = tmp_path / "user_profile.yaml"
    roles = tmp_path / "target_roles.yaml"
    profile.write_text(yaml.dump({"personal": {"full_name": "Jane Doe"}}))
    roles.write_text(yaml.dump({"resume_based": [], "exploratory": []}))

    monkeypatch.setattr("src.web.app._PROFILE_PATH", profile)
    monkeypatch.setattr("src.web.app._ROLES_PATH", roles)

    return TestClient(app)


class TestSettingsGet:
    def test_returns_200(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_contains_profile_content(self, client):
        resp = client.get("/settings")
        assert "Jane Doe" in resp.text

    def test_contains_roles_content(self, client):
        resp = client.get("/settings")
        assert "resume_based" in resp.text


class TestSettingsPostProfile:
    def test_saves_updated_profile(self, tmp_path, monkeypatch):
        profile = tmp_path / "user_profile.yaml"
        roles = tmp_path / "target_roles.yaml"
        profile.write_text(yaml.dump({"personal": {"full_name": "Old Name"}}))
        roles.write_text(yaml.dump({"resume_based": []}))
        monkeypatch.setattr("src.web.app._PROFILE_PATH", profile)
        monkeypatch.setattr("src.web.app._ROLES_PATH", roles)

        client = TestClient(app)
        new_yaml = yaml.dump({"personal": {"full_name": "New Name"}})
        resp = client.post("/settings/profile", data={"content": new_yaml})
        assert resp.status_code in (200, 303)
        assert "New Name" in profile.read_text()

    def test_rejects_invalid_yaml(self, client):
        resp = client.post("/settings/profile", data={"content": ": : invalid: {"})
        assert resp.status_code == 400


class TestSettingsPostRoles:
    def test_saves_updated_roles(self, tmp_path, monkeypatch):
        profile = tmp_path / "user_profile.yaml"
        roles = tmp_path / "target_roles.yaml"
        profile.write_text(yaml.dump({"personal": {}}))
        roles.write_text(yaml.dump({"resume_based": []}))
        monkeypatch.setattr("src.web.app._PROFILE_PATH", profile)
        monkeypatch.setattr("src.web.app._ROLES_PATH", roles)

        client = TestClient(app)
        new_yaml = yaml.dump({"resume_based": [{"title": "ML Engineer"}]})
        resp = client.post("/settings/roles", data={"content": new_yaml})
        assert resp.status_code in (200, 303)
        saved = yaml.safe_load(roles.read_text())
        assert saved["resume_based"][0]["title"] == "ML Engineer"

    def test_rejects_invalid_yaml(self, client):
        resp = client.post("/settings/roles", data={"content": "{{broken"})
        assert resp.status_code == 400


class TestCvUpload:
    def test_upload_valid_md(self, tmp_path, monkeypatch):
        cv_path = tmp_path / "cv.md"
        monkeypatch.setattr("src.web.app._CV_PATH", cv_path)
        client = TestClient(app)
        resp = client.post(
            "/settings/upload-cv",
            files={"cv_file": ("my_cv.md", b"# My CV\nExperience...", "text/markdown")},
        )
        assert resp.status_code == 200
        assert "uploaded successfully" in resp.text
        assert cv_path.read_bytes() == b"# My CV\nExperience..."

    def test_rejects_non_md(self, tmp_path, monkeypatch):
        cv_path = tmp_path / "cv.md"
        monkeypatch.setattr("src.web.app._CV_PATH", cv_path)
        client = TestClient(app)
        resp = client.post(
            "/settings/upload-cv",
            files={"cv_file": ("resume.pdf", b"%PDF", "application/pdf")},
        )
        assert resp.status_code == 200
        assert "Please upload a .md" in resp.text

    def test_cv_status_missing(self, tmp_path, monkeypatch):
        cv_path = tmp_path / "cv.md"
        monkeypatch.setattr("src.web.app._CV_PATH", cv_path)
        client = TestClient(app)
        resp = client.get("/settings/cv-status")
        assert resp.status_code == 200
        assert "No CV" in resp.text

    def test_cv_status_present(self, tmp_path, monkeypatch):
        cv_path = tmp_path / "cv.md"
        cv_path.write_text("# CV")
        monkeypatch.setattr("src.web.app._CV_PATH", cv_path)
        client = TestClient(app)
        resp = client.get("/settings/cv-status")
        assert resp.status_code == 200
        assert "data/cv.md" in resp.text
