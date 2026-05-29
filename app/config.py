from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Settings
    APP_NAME: str = "AutoCRM"
    DEBUG: bool = True
    
    # Database Settings
    DATABASE_URL: Optional[str] = None
    
    # LLM Settings (supports any LLM provider)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4"  # Model name (e.g., gpt-4, claude-3, gemini-pro, llama-3)
    LLM_BASE_URL: Optional[str] = None  # Custom API endpoint for local/alternative LLMs
    
    # JWT Settings
    JWT_SECRET_KEY: str = Field(
        default="your-secret-key-change-in-production-min-32-chars",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY", "jwt_secret_key"),
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
    CALL_RECORDINGS_DIR: str = "storage/recordings"
    CALL_RECORDINGS_URL_BASE: str = "/static/recordings"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

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
