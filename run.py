from app.api import app
from app.config import settings

if __name__ == "__main__":
    if settings.app_env == "production" and not settings.admin_key:
        raise SystemExit("Defina LICENSE_API_KEY antes de iniciar em produção")
    app.run(host=settings.host, port=settings.port, debug=False)
