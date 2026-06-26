from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Settings
    APP_NAME: str = "AutoCRM"
    DEBUG: bool = True
    
    # Database Settings
    DATABASE_URL: Optional[str] = None
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 3600
    DB_MAX_CONCURRENT_OPERATIONS: int = 5

    # Supabase Storage
    SUPABASE_URL: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_URL", "PROJECT_URL"),
    )
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "SECRET_KEY"),
    )
    SUPABASE_PUBLISHABLE_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "PUBLISHABLE_KEY"),
    )
    SUPABASE_AVATAR_BUCKET: str = "avatars"
    SUPABASE_MAX_AVATAR_BYTES: int = 2_000_000

    # Local avatar storage
    AVATAR_STORAGE_DIR: str = "storage/avatars"
    AVATAR_PUBLIC_BASE_URL: str = "http://localhost:8000"
    
    # LLM Settings (supports any LLM provider)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4"  # Model name (e.g., gpt-4, claude-3, gemini-pro, llama-3)
    LLM_BASE_URL: Optional[str] = None  # Custom API endpoint for local/alternative LLMs
    
    # JWT Settings
    JWT_SECRET_KEY: str = Field(
        default="your-secret-key-change-in-production-min-32-chars",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "jwt_secret_key", "SECRET_KEY"),
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM", "ALGORITHM", "jwt_algorithm"),
    )
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            "jwt_access_token_expire_minutes",
        ),
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        validation_alias=AliasChoices(
            "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
            "REFRESH_TOKEN_EXPIRE_DAYS",
            "jwt_refresh_token_expire_days",
        ),
    )
    # Security hardening settings
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100  # Tuned down from 120 to prevent overload
    RATE_LIMIT_MAX_QUEUE_SIZE: int = 500  # Max queued requests before rejecting
    MAX_REQUEST_SIZE_BYTES: int = 1_048_576
    SECURITY_HEADERS_ENABLED: bool = True


    # Permissions storage (local JSON files)
    PERMISSIONS_STORAGE_DIR: str = "storage/permissions"

    # Mailjet (email invitations + notifications)
    MAILJET_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MAILJET_API_KEY", "MJ_APIKEY", "api_key"),
    )
    MAILJET_SECRET_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MAILJET_SECRET_KEY", "MJ_SECRET", "secret_key"),
    )
    MAILJET_SENDER_EMAIL: Optional[str] = None
    MAILJET_SENDER_NAME: str = "AutoCRM"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    INVITE_TOKEN_TTL_HOURS: int = 72
    RESET_TOKEN_TTL_MINUTES: int = 30

    # Call module settings
    CALL_ROOM_TOKEN_TTL_MINUTES: int = 15
    CALL_RECORDINGS_DIR: str = Field(
        default="storage/recordings",
        validation_alias=AliasChoices("CALL_RECORDINGS_DIR", "AUTOCRM_RECORDINGS_DIR", "RECORDINGS_STORAGE_DIR"),
    )
    CALL_RECORDINGS_URL_BASE: str = "/static/recordings"

    # AI service transcription notification
    AI_SERVICE_BASE_URL: str = "http://localhost:8001"
    AI_TRANSCRIPTION_NOTIFY_ENABLED: bool = True
    AI_SERVICE_NOTIFY_TIMEOUT_SECONDS: int = 10
    AI_SERVICE_WEBHOOK_TOKEN: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_flag(cls, value):
        if isinstance(value, str) and value.strip().lower() in {"release", "prod", "production"}:
            return False
        return value

    @property
    def jwt_secret_key(self) -> str:
        return self.JWT_SECRET_KEY

    @property
    def jwt_algorithm(self) -> str:
        return self.JWT_ALGORITHM

    @property
    def jwt_access_token_expire_minutes(self) -> int:
        return self.JWT_ACCESS_TOKEN_EXPIRE_MINUTES

    @property
    def jwt_refresh_token_expire_days(self) -> int:
        return self.JWT_REFRESH_TOKEN_EXPIRE_DAYS


settings = Settings()
