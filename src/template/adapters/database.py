"""Database adapter"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from template.settings.database_settings import DatabaseSettings

settings = DatabaseSettings()


# Add retry logic for initial connection
def get_engine():
    """Get database engine."""
    return create_engine(
        settings.url,
        echo=settings.echo,
        pool_pre_ping=True,  # Enables connection health checks
    )


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
