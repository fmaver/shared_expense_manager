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
        # Headroom for the frontend's parallel dashboard fetches — the
        # default 5+10 exhausts under bursts of concurrent ledger requests.
        pool_size=10,
        max_overflow=20,
        pool_recycle=300,  # Recycle idle connections before Neon closes them server-side
    )


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # pylint: disable=invalid-name


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
