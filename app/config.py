from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Application Settings
    APP_NAME: str = "AutoCRM"
    DEBUG: bool = True
    
    # Database Settings (Supabase)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    DATABASE_URL: Optional[str] = None
    
    # LLM Settings (supports any LLM provider)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4"  # Model name (e.g., gpt-4, claude-3, gemini-pro, llama-3)
    LLM_BASE_URL: Optional[str] = None  # Custom API endpoint for local/alternative LLMs
    
    # JWT Settings
    jwt_secret_key: str = "your-secret-key-change-in-production-min-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
