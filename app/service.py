from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def normalize_key(value: str) -> str:
    return "".join(str(value).strip().upper().split())


def key_hash(value: str) -> str:
    return hashlib.sha256(normalize_key(value).encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def expired(value: str | None) -> bool:
    if not value:
        return False
    return datetime.fromisoformat(value.replace("Z", "+00:00")) <= now_utc()


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": record.get("plan", "unknown"),
        "status": record.get("status", "unknown"),
        "expires_at": record.get("expires_at"),
        "max_devices": int(record.get("max_devices", 1)),
        "device_count": len(record.get("devices", [])),
    }


def activate(store, key: str, hwid: str) -> dict[str, Any]:
    data = store.load()
    record = data.get("licenses", {}).get(key_hash(key))
    if not record or record.get("status") != "active":
        return {"success": False, "message": "Licença inválida"}
    if expired(record.get("expires_at")):
        return {"success": False, "message": "Licença expirada"}

    hwid = str(hwid).strip().upper()
    devices = record.setdefault("devices", [])
    max_devices = int(record.get("max_devices", 1))
    if hwid not in devices and len(devices) >= max_devices:
        return {"success": False, "message": "Limite de dispositivos atingido"}
    if hwid not in devices:
        devices.append(hwid)
        store.save(data)
    return {"success": True, **public_record(record)}


def validate(store, key: str, hwid: str) -> dict[str, Any]:
    data = store.load()
    record = data.get("licenses", {}).get(key_hash(key))
    valid = bool(
        record
        and record.get("status") == "active"
        and not expired(record.get("expires_at"))
        and str(hwid).strip().upper() in record.get("devices", [])
    )
    return {"valid": valid, **(public_record(record) if valid else {})}
