from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    # Application Settings
    APP_NAME: str = Field(default="AutoCRM", validation_alias=AliasChoices("APP_NAME"))
    DEBUG: bool = Field(default=True, validation_alias=AliasChoices("DEBUG"))
    
    # Database Settings
    DATABASE_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("DATABASE_URL"))
    DB_POOL_SIZE: int = Field(default=5, validation_alias=AliasChoices("DB_POOL_SIZE"))
    DB_MAX_OVERFLOW: int = Field(default=5, validation_alias=AliasChoices("DB_MAX_OVERFLOW"))
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=30, validation_alias=AliasChoices("DB_POOL_TIMEOUT_SECONDS"))
    DB_POOL_RECYCLE_SECONDS: int = Field(default=3600, validation_alias=AliasChoices("DB_POOL_RECYCLE_SECONDS"))
    DB_MAX_CONCURRENT_OPERATIONS: int = Field(default=5, validation_alias=AliasChoices("DB_MAX_CONCURRENT_OPERATIONS"))
    LEAD_SCORE_SWEEP_CONCURRENCY: int = Field(default=5, validation_alias=AliasChoices("LEAD_SCORE_SWEEP_CONCURRENCY"))

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
    SUPABASE_AVATAR_BUCKET: str = Field(default="avatars", validation_alias=AliasChoices("SUPABASE_AVATAR_BUCKET"))
    SUPABASE_MAX_AVATAR_BYTES: int = Field(default=2_000_000, validation_alias=AliasChoices("SUPABASE_MAX_AVATAR_BYTES"))

    # Local avatar storage
    AVATAR_STORAGE_DIR: str = Field(default="storage/avatars", validation_alias=AliasChoices("AVATAR_STORAGE_DIR"))
    AVATAR_PUBLIC_BASE_URL: str = Field(default="http://localhost:8000", validation_alias=AliasChoices("AVATAR_PUBLIC_BASE_URL"))
    
    # LLM Settings (supports any LLM provider)
    LLM_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY"))
    LLM_MODEL: str = Field(default="", validation_alias=AliasChoices("LLM_MODEL"))
    LLM_BASE_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("LLM_BASE_URL"))
    
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
    RATE_LIMIT_ENABLED: bool = Field(default=True, validation_alias=AliasChoices("RATE_LIMIT_ENABLED"))
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=100, validation_alias=AliasChoices("RATE_LIMIT_REQUESTS_PER_MINUTE"))
    RATE_LIMIT_MAX_QUEUE_SIZE: int = Field(default=500, validation_alias=AliasChoices("RATE_LIMIT_MAX_QUEUE_SIZE"))
    MAX_REQUEST_SIZE_BYTES: int = Field(default=1_048_576, validation_alias=AliasChoices("MAX_REQUEST_SIZE_BYTES"))
    SECURITY_HEADERS_ENABLED: bool = Field(default=True, validation_alias=AliasChoices("SECURITY_HEADERS_ENABLED"))


    # Permissions storage (local JSON files)
    PERMISSIONS_STORAGE_DIR: str = Field(default="storage/permissions", validation_alias=AliasChoices("PERMISSIONS_STORAGE_DIR"))

    # Mailjet (email invitations + notifications)
    MAILJET_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MAILJET_API_KEY", "MJ_APIKEY", "api_key"),
    )
    MAILJET_SECRET_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MAILJET_SECRET_KEY", "MJ_SECRET", "secret_key"),
    )
    MAILJET_SENDER_EMAIL: Optional[str] = Field(default=None, validation_alias=AliasChoices("MAILJET_SENDER_EMAIL"))
    MAILJET_SENDER_NAME: str = Field(default="AutoCRM", validation_alias=AliasChoices("MAILJET_SENDER_NAME"))
    FRONTEND_BASE_URL: str = Field(default="http://localhost:5173", validation_alias=AliasChoices("FRONTEND_BASE_URL"))
    INVITE_TOKEN_TTL_HOURS: int = Field(default=72, validation_alias=AliasChoices("INVITE_TOKEN_TTL_HOURS"))
    RESET_TOKEN_TTL_MINUTES: int = Field(default=30, validation_alias=AliasChoices("RESET_TOKEN_TTL_MINUTES"))

    # Metered video room settings retained for deployments that provide them.
    METERED_DOMAIN: Optional[str] = Field(default=None, validation_alias=AliasChoices("METERED_DOMAIN"))
    METERED_SECRET_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("METERED_SECRET_KEY"))

    # Call module settings
    CALL_ROOM_TOKEN_TTL_MINUTES: int = Field(default=15, validation_alias=AliasChoices("CALL_ROOM_TOKEN_TTL_MINUTES"))
    CALL_RECORDINGS_DIR: str = Field(
        default="storage/recordings",
        validation_alias=AliasChoices("CALL_RECORDINGS_DIR", "AUTOCRM_RECORDINGS_DIR", "RECORDINGS_STORAGE_DIR"),
    )
    CALL_RECORDINGS_URL_BASE: str = Field(default="/api/calls", validation_alias=AliasChoices("CALL_RECORDINGS_URL_BASE"))
    CALL_RECORDING_CHUNK_MAX_BYTES: int = Field(default=5_000_000, validation_alias=AliasChoices("CALL_RECORDING_CHUNK_MAX_BYTES"))
    CALL_RECORDING_MAX_BYTES: int = Field(default=100_000_000, validation_alias=AliasChoices("CALL_RECORDING_MAX_BYTES"))

    # Import limits
    IMPORT_MAX_FILE_BYTES: int = Field(default=5_000_000, validation_alias=AliasChoices("IMPORT_MAX_FILE_BYTES"))
    IMPORT_MAX_ROWS: int = Field(default=5_000, validation_alias=AliasChoices("IMPORT_MAX_ROWS"))

    # AI service transcription notification
    AI_SERVICE_BASE_URL: str = Field(default="http://localhost:8001", validation_alias=AliasChoices("AI_SERVICE_BASE_URL"))
    AI_TRANSCRIPTION_NOTIFY_ENABLED: bool = Field(default=True, validation_alias=AliasChoices("AI_TRANSCRIPTION_NOTIFY_ENABLED"))
    AI_SERVICE_NOTIFY_TIMEOUT_SECONDS: int = Field(default=10, validation_alias=AliasChoices("AI_SERVICE_NOTIFY_TIMEOUT_SECONDS"))
    AI_SERVICE_WEBHOOK_TOKEN: Optional[str] = Field(default=None, validation_alias=AliasChoices("AI_SERVICE_WEBHOOK_TOKEN"))

    model_config = SettingsConfigDict(env_file=ENV_FILE, case_sensitive=True, extra="ignore")

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
