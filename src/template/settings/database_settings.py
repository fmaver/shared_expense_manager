"""Database settings"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    database_env: str = os.getenv("DATABASE_ENV", "QA")
    url: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.database_env == "QA":
            # Local development with Docker
            self.url = os.getenv("QA_DATABASE_URL", "postgresql://postgres:postgres@db:5432/expense_manager")
        elif self.database_env == "PROD":
            # Production environment (Render)
            self.url = os.getenv("DATABASE_URL")  # Render provides this environment variable
            if not self.url:
                raise ValueError("DATABASE_URL environment variable is required in production")
        else:
            self.url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/expense_manager")

    echo: bool = False

    model_config = SettingsConfigDict(env_prefix="DATABASE_")
