"""Database adapter"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.settings.database_settings import DatabaseSettings

# Use in-memory SQLite for testing if TEST_ENV is set
if os.getenv("TEST_ENV") == "true":
    SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    settings = DatabaseSettings()
    engine = create_engine(
        settings.url,
        echo=settings.echo,
        pool_pre_ping=True,  # Enables connection health checks
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
