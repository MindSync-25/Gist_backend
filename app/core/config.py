from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Gist Backend"
    app_env: str = "development"
    app_port: int = 8000
    cors_origins: str = "http://localhost:8081,http://localhost:3000"

    # Full connection URL (e.g. Supabase pgBouncer URL). Takes precedence over individual fields.
    # Accepts either DATABASE_URL or DATABASE_URL_OVERRIDE env var.
    database_url_override: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL_OVERRIDE", "DATABASE_URL"),
    )
    # Optional manual override. If false, runtime logic can still auto-detect transaction
    # pooler URLs (e.g., Supabase pooler on 6543) and enable pgBouncer-safe mode.
    db_use_pgbouncer: bool = False

    db_host: str = ""
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str = ""
    db_password: str = ""
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout: int = 30

    jwt_secret: str = Field(default="change-me")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_minutes: int = 20160

    otp_expire_minutes: int = 10

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    google_oauth_client_id: str = ""
    apple_oauth_client_id: str = ""

    # AWS / S3
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = "gist-comics-ap-south-1"
    s3_user_uploads_prefix: str = "user-uploads/"
    s3_presign_expiry_seconds: int = 300  # 5 min to complete upload
    s3_content_presign_expiry_seconds: int = 86400  # 24 hr for serving feed images

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def db_use_pgbouncer_effective(self) -> bool:
        if self.db_use_pgbouncer:
            return True

        url = self.database_url.strip()
        if not url:
            return False

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port

        # Supabase transaction pooler commonly uses the pooler host and port 6543.
        if host.endswith("pooler.supabase.com") and port == 6543:
            return True

        # Generic escape hatch for any environment that appends this URL flag.
        if "pgbouncer=true" in url.lower():
            return True

        return False

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
