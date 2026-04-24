from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "NewsGroup Connect"
    app_version: str = "0.1.0"
    debug: bool = False
    testing: bool = False

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/newsgroup"
    database_pool_size: int = 5
    database_max_overflow: int = 10

    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@newsgroup.local"

    s3_endpoint_url: str | None = None
    s3_bucket_name: str = "newsgroup-media"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    cdn_base_url: str = ""

    max_upload_size_mb: int = 10
    allowed_content_types: list[str] = ["image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
