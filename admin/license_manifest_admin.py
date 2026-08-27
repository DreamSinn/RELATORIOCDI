from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.service import key_hash


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "licenses.json"


def new_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(5))


def expires_after(days: int) -> str:
    if days < 0:
        raise ValueError("--days não pode ser negativo")
    value = datetime.now(timezone.utc) + timedelta(days=days)
    return value.isoformat().replace("+00:00", "Z")


def load_manifest(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {"schema": 1, "licenses": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("licenses"), dict):
        raise ValueError("Manifesto inválido: esperados schema=1 e licenses como objeto")
    return data


def save_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def create(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    data = load_manifest(path)
    key = args.key or new_key()
    digest = key_hash(key)
    if digest in data["licenses"]:
        raise SystemExit("Essa licença já existe no manifesto")

    data["licenses"][digest] = {
        "status": "active",
        "plan": args.plan,
        "expires_at": expires_after(args.days),
        "max_devices": args.max_devices,
        "devices": [],
    }
    save_manifest(path, data)
    print(f"LICENSE_KEY={key}")
    print(f"KEY_HASH={digest}")
    print(f"MANIFEST={path}")


def revoke(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    data = load_manifest(path)
    digest = args.hash or key_hash(args.key)
    record = data["licenses"].get(digest)
    if record is None:
        raise SystemExit("Licença não encontrada")
    record["status"] = "revoked"
    save_manifest(path, data)
    print(f"REVOKED_HASH={digest}")
    print(f"MANIFEST={path}")


def list_licenses(args: argparse.Namespace) -> None:
    data = load_manifest(Path(args.manifest))
    for digest, record in data["licenses"].items():
        print(json.dumps({"hash": digest, **record}, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Administração local do manifesto de licenças FI$H"
    )
    root.add_argument(
        "--manifest", default=str(DEFAULT_MANIFEST), help="caminho do manifesto JSON"
    )
    commands = root.add_subparsers(dest="command", required=True)

    create_parser = commands.add_parser("create", help="cria uma licença")
    create_parser.add_argument("--key", help="chave específica; se omitida, gera uma nova")
    create_parser.add_argument("--days", type=int, default=30)
    create_parser.add_argument("--plan", default="monthly")
    create_parser.add_argument("--max-devices", type=int, default=1)
    create_parser.set_defaults(handler=create)

    revoke_parser = commands.add_parser("revoke", help="revoga uma licença")
    revoke_parser.add_argument("--key", default="", help="chave original da licença")
    revoke_parser.add_argument("--hash", default="", help="hash SHA-256 da licença")
    revoke_parser.set_defaults(handler=revoke)

    list_parser = commands.add_parser("list", help="lista hashes e metadados")
    list_parser.set_defaults(handler=list_licenses)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "revoke" and bool(args.key) == bool(args.hash):
        raise SystemExit("Use exatamente uma opção: --key ou --hash")
    if args.command == "create" and args.max_devices < 1:
        raise SystemExit("--max-devices deve ser pelo menos 1")
    args.handler(args)


if __name__ == "__main__":
    main()
