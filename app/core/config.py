from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Gist Backend"
    app_env: str = "development"
    app_port: int = 8000
    cors_origins: str = "http://localhost:8081,http://localhost:3000"

    db_host: str
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str
    db_password: str
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout: int = 30

    jwt_secret: str = Field(default="change-me")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_minutes: int = 20160

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
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
