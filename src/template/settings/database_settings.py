"""Database settings"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    url: str = "postgresql://postgres:postgres@db:5432/expense_manager"
    echo: bool = False

    model_config = SettingsConfigDict(env_prefix="DATABASE_")
