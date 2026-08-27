from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


class LicenseStore:
    def load(self) -> dict[str, Any]:
        raise NotImplementedError

    def save(self, data: dict[str, Any]) -> None:
        raise NotImplementedError


class LocalStore(LicenseStore):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": 1, "licenses": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)


class GistStore(LicenseStore):
    def __init__(self, gist_id: str, filename: str, token: str):
        if not gist_id or not filename or not token:
            raise ValueError("GIST_ID, GIST_FILENAME e GITHUB_TOKEN são obrigatórios")
        self.url = f"https://api.github.com/gists/{gist_id}"
        self.filename = filename
        self.token = token

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2026-03-10",
        }

    def load(self) -> dict[str, Any]:
        response = requests.get(self.url, headers=self.headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        file_info = payload["files"][self.filename]
        if file_info.get("truncated"):
            raise RuntimeError("O arquivo do Gist excedeu o limite da API")
        return json.loads(file_info["content"])

    def save(self, data: dict[str, Any]) -> None:
        body = {"files": {self.filename: {"content": json.dumps(data, indent=2, ensure_ascii=False)}}}
        response = requests.patch(
            self.url,
            headers={**self.headers, "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
        response.raise_for_status()
