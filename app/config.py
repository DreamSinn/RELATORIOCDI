import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8080"))
    admin_key: str = os.getenv("LICENSE_API_KEY", "")
    gist_id: str = os.getenv("GIST_ID", "")
    gist_filename: str = os.getenv("GIST_FILENAME", "licenses.json")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    offline_grace_hours: int = int(os.getenv("OFFLINE_GRACE_HOURS", "24"))

settings = Settings()
