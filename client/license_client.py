from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

import requests


def _command(command: str) -> str:
    try:
        output = subprocess.check_output(command, shell=True, text=True, stderr=subprocess.DEVNULL)
        values = [line.strip() for line in output.splitlines() if line.strip()]
        return values[-1] if values else ""
    except Exception:
        return ""


def get_hwid() -> str:
    parts = [
        platform.node(),
        _command("wmic csproduct get uuid"),
        _command("wmic bios get serialnumber"),
    ]
    raw = "|".join(value.upper() for value in parts if value)
    if not raw:
        raw = platform.node().upper() or "UNKNOWN-MACHINE"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


class LicenseClient:
    def __init__(self, api_base: str, cache_path: str | Path):
        self.api_base = api_base.rstrip("/")
        self.cache_path = Path(cache_path)

    def activate(self, key: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.api_base}/v1/license/activate",
            json={"key": key, "hwid": get_hwid()},
            timeout=10,
        )
        data = response.json()
        if response.ok and data.get("success"):
            self._save_cache(key, data)
        return data

    def validate(self, key: str | None = None) -> dict[str, Any]:
        cached = self._load_cache()
        key = key or cached.get("license_key", "")
        if not key:
            return {"valid": False, "message": "nenhuma licença configurada"}
        response = requests.post(
            f"{self.api_base}/v1/license/validate",
            json={"key": key, "hwid": get_hwid()},
            timeout=10,
        )
        data = response.json()
        if response.ok and data.get("valid"):
            self._save_cache(key, data)
        return data

    def _save_cache(self, key: str, result: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({"license_key": key, **result}, indent=2), encoding="utf-8")

    def _load_cache(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
