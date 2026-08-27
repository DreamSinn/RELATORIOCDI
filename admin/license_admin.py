from __future__ import annotations

import argparse
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

import requests


def new_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(5))


def main():
    parser = argparse.ArgumentParser(description="Administração de licenças FI$H")
    parser.add_argument("--api", default=os.getenv("LICENSE_ADMIN_API", "http://127.0.0.1:8080"))
    parser.add_argument("--admin-key", default=os.getenv("LICENSE_API_KEY", ""))
    parser.add_argument("--key", default="", help="chave; se omitida, uma nova é gerada")
    parser.add_argument("--plan", default="monthly")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-devices", type=int, default=1)
    args = parser.parse_args()
    if not args.admin_key:
        raise SystemExit("Defina --admin-key ou LICENSE_API_KEY")
    key = args.key or new_key()
    expires = (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat().replace("+00:00", "Z")
    response = requests.post(
        args.api.rstrip("/") + "/v1/admin/licenses",
        headers={"X-Admin-Key": args.admin_key},
        json={"key": key, "plan": args.plan, "expires_at": expires, "max_devices": args.max_devices},
        timeout=10,
    )
    print(response.text)
    response.raise_for_status()
    print(f"LICENSE_KEY={key}")


if __name__ == "__main__":
    main()
