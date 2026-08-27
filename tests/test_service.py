from datetime import datetime, timedelta, timezone

from app.service import activate, key_hash, validate
from app.store import LocalStore


def future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def make_store(tmp_path):
    return LocalStore(tmp_path / "licenses.json")


def test_activation_and_same_device(tmp_path):
    store = make_store(tmp_path)
    store.save({"schema": 1, "licenses": {key_hash("ABC"): {"status": "active", "expires_at": future(), "max_devices": 1, "devices": []}}})
    assert activate(store, "abc", "HWID-1")["success"] is True
    assert activate(store, "ABC", "HWID-1")["success"] is True
    assert validate(store, "ABC", "HWID-1")["valid"] is True


def test_device_limit(tmp_path):
    store = make_store(tmp_path)
    store.save({"schema": 1, "licenses": {key_hash("ABC"): {"status": "active", "expires_at": future(), "max_devices": 1, "devices": []}}})
    assert activate(store, "ABC", "HWID-1")["success"] is True
    assert activate(store, "ABC", "HWID-2")["success"] is False


def test_expired_license(tmp_path):
    store = make_store(tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    store.save({"schema": 1, "licenses": {key_hash("ABC"): {"status": "active", "expires_at": past, "max_devices": 1, "devices": []}}})
    assert activate(store, "ABC", "HWID-1")["success"] is False
