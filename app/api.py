from __future__ import annotations

from functools import wraps
from pathlib import Path
from flask import Flask, jsonify, request

from .config import settings
from .service import activate, key_hash, validate
from .store import GistStore, LocalStore

BASE_DIR = Path(__file__).resolve().parents[1]


def make_store():
    if settings.gist_id and settings.github_token:
        return GistStore(settings.gist_id, settings.gist_filename, settings.github_token)
    return LocalStore(BASE_DIR / "data" / "licenses.local.json")


store = make_store()
app = Flask(__name__)


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        supplied = request.headers.get("X-Admin-Key", "")
        if not settings.admin_key or supplied != settings.admin_key:
            return jsonify(error="não autorizado"), 401
        return view(*args, **kwargs)
    return wrapped


@app.get("/health")
def health():
    return jsonify(ok=True, environment=settings.app_env)


@app.post("/v1/license/activate")
def license_activate():
    body = request.get_json(silent=True) or {}
    key = str(body.get("key", ""))
    hwid = str(body.get("hwid", ""))
    if not key or not hwid or len(hwid) > 128:
        return jsonify(success=False, message="dados de ativação inválidos"), 400
    result = activate(store, key, hwid)
    return jsonify(result), (200 if result["success"] else 403)


@app.post("/v1/license/validate")
def license_validate():
    body = request.get_json(silent=True) or {}
    key = str(body.get("key", ""))
    hwid = str(body.get("hwid", ""))
    if not key or not hwid:
        return jsonify(valid=False, message="dados inválidos"), 400
    result = validate(store, key, hwid)
    return jsonify(result), (200 if result["valid"] else 403)


@app.post("/v1/admin/licenses")
@require_admin
def create_license():
    body = request.get_json(silent=True) or {}
    raw_key = str(body.get("key", "")).strip().upper()
    if not raw_key:
        return jsonify(error="key obrigatória"), 400
    data = store.load()
    data.setdefault("licenses", {})[key_hash(raw_key)] = {
        "status": body.get("status", "active"),
        "plan": body.get("plan", "monthly"),
        "expires_at": body.get("expires_at"),
        "max_devices": max(1, int(body.get("max_devices", 1))),
        "devices": [],
    }
    store.save(data)
    return jsonify(created=True, key_hash=key_hash(raw_key)), 201


@app.patch("/v1/admin/licenses/<license_id>")
@require_admin
def update_license(license_id):
    data = store.load()
    record = data.get("licenses", {}).get(license_id)
    if not record:
        return jsonify(error="licença não encontrada"), 404
    body = request.get_json(silent=True) or {}
    for field in ("status", "plan", "expires_at", "max_devices"):
        if field in body:
            record[field] = body[field]
    if "max_devices" in record:
        record["max_devices"] = max(1, int(record["max_devices"]))
    if body.get("clear_devices"):
        record["devices"] = []
    store.save(data)
    return jsonify(updated=True, license=license_id)


if __name__ == "__main__":
    if settings.app_env == "production" and not settings.admin_key:
        raise SystemExit("LICENSE_API_KEY deve ser definido em produção")
    app.run(host=settings.host, port=settings.port, debug=False)
