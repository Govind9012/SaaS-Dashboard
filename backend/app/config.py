import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "SaaS Dashboard API"
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./saas.db",
    )
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-me-secret")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120")
    )
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "change-me-webhook-secret")
    admin_email: str = os.getenv("ADMIN_EMAIL", "admin@saas.local")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "AdminPass123!")


settings = Settings()
