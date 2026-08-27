from __future__ import annotations

from datetime import datetime, timedelta, timezone

from client.license_client import LicenseClient, key_hash


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def make_client(monkeypatch, record: dict | None):
    licenses = {}
    if record is not None:
        licenses[key_hash("DEMO1-TEST2-KEY33-ABCDE-12345")] = record
    payload = {"schema": 1, "licenses": licenses}
    monkeypatch.setattr(
        "client.license_client.requests.get",
        lambda *args, **kwargs: FakeResponse(payload),
    )
    return LicenseClient(
        manifest_url="https://example.invalid/licenses.json",
        cache_path="/tmp/fish-test-license-cache.json",
    )


def test_active_license_is_accepted(monkeypatch):
    client = make_client(
        monkeypatch,
        {
            "status": "active",
            "plan": "demo",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "max_devices": 1,
            "devices": [],
        },
    )
    result = client.activate("DEMO1-TEST2-KEY33-ABCDE-12345")
    assert result["success"] is True
    assert result["plan"] == "demo"


def test_unknown_license_is_rejected(monkeypatch):
    client = make_client(monkeypatch, None)
    result = client.activate("WRONG-KEY-00000-00000-00000")
    assert result["success"] is False
    assert result["message"] == "Licença inválida"


def test_expired_license_is_rejected(monkeypatch):
    client = make_client(
        monkeypatch,
        {
            "status": "active",
            "plan": "demo",
            "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "max_devices": 1,
            "devices": [],
        },
    )
    result = client.activate("DEMO1-TEST2-KEY33-ABCDE-12345")
    assert result["success"] is False
    assert result["message"] == "Licença expirada"


def test_revoked_license_is_rejected(monkeypatch):
    client = make_client(
        monkeypatch,
        {
            "status": "revoked",
            "plan": "demo",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "max_devices": 1,
            "devices": [],
        },
    )
    result = client.activate("DEMO1-TEST2-KEY33-ABCDE-12345")
    assert result["success"] is False
    assert result["message"] == "Licença inválida"
