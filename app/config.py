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
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
