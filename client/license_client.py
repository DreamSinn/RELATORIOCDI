from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/DreamSinn/RELATORIOCDI/main/data/licenses.json"
)


def _command(command: str) -> str:
    try:
        output = subprocess.check_output(command, shell=True, text=True, stderr=subprocess.DEVNULL)
        values = [line.strip() for line in output.splitlines() if line.strip()]
        return values[-1] if values else ""
    except Exception:
        return ""


def get_hwid() -> str:
    parts = [platform.node(), _command("wmic csproduct get uuid"), _command("wmic bios get serialnumber")]
    raw = "|".join(value.upper() for value in parts if value)
    if not raw:
        raw = platform.node().upper() or "UNKNOWN-MACHINE"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def normalize_key(value: str) -> str:
    return "".join(str(value).strip().upper().split())


def key_hash(value: str) -> str:
    return hashlib.sha256(normalize_key(value).encode("utf-8")).hexdigest()


def _not_expired(value: str | None) -> bool:
    if not value:
        return True
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except ValueError:
        return False


class LicenseClient:
    def __init__(
        self,
        api_base: str | None = None,
        cache_path: str | Path = "license_cache.json",
        manifest_url: str = DEFAULT_MANIFEST_URL,
    ):
        self.api_base = api_base.rstrip("/") if api_base else ""
        self.cache_path = Path(cache_path)
        self.manifest_url = manifest_url

    def activate(self, key: str) -> dict[str, Any]:
        if self.api_base:
            response = requests.post(
                f"{self.api_base}/v1/license/activate",
                json={"key": key, "hwid": get_hwid()},
                timeout=10,
            )
            data = response.json()
        else:
            data = self._validate_manifest_key(key)
        if data.get("success"):
            self._save_cache(key, data)
        return data

    def validate(self, key: str | None = None) -> dict[str, Any]:
        cached = self._load_cache()
        key = key or cached.get("license_key", "")
        if not key:
            return {"valid": False, "message": "nenhuma licença configurada"}

        if self.api_base:
            response = requests.post(
                f"{self.api_base}/v1/license/validate",
                json={"key": key, "hwid": get_hwid()},
                timeout=10,
            )
            data = response.json()
        else:
            data = self._validate_manifest_key(key, validation=True)
        if data.get("valid"):
            self._save_cache(key, data)
        return data

    def _validate_manifest_key(self, key: str, validation: bool = False) -> dict[str, Any]:
        try:
            response = requests.get(self.manifest_url, timeout=10)
            response.raise_for_status()
            manifest = response.json()
        except (requests.RequestException, ValueError) as exc:
            return {"success": False, "valid": False, "message": f"manifesto indisponível: {exc}"}

        if manifest.get("schema") != 1 or not isinstance(manifest.get("licenses"), dict):
            return {"success": False, "valid": False, "message": "manifesto inválido"}

        record = manifest["licenses"].get(key_hash(key))
        if not record or record.get("status") != "active":
            return {"success": False, "valid": False, "message": "Licença inválida"}
        if not _not_expired(record.get("expires_at")):
            return {"success": False, "valid": False, "message": "Licença expirada"}

        result: dict[str, Any] = {
            "plan": record.get("plan", "unknown"),
            "status": "active",
            "expires_at": record.get("expires_at"),
            "max_devices": int(record.get("max_devices", 1)),
            "device_count": len(record.get("devices", [])),
        }
        if validation:
            return {"valid": True, **result}
        return {"success": True, **result}

    def _save_cache(self, key: str, result: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"license_key": key, "hwid": get_hwid(), **result}
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_cache(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
