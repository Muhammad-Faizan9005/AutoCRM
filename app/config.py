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
    
    # OpenAI Settings for AI features
    OPENAI_API_KEY: Optional[str] = None
    
    # JWT Settings
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
