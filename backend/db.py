from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from config import settings


def normalize_sync_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return f"postgresql+psycopg2://{url.split('://', 1)[1]}"
    if url.startswith("postgres://"):
        return f"postgresql://{url[len('postgres://') :]}"
    return url


SYNC_DATABASE_URL = normalize_sync_database_url(settings.DATABASE_URL)

engine = create_engine(
    SYNC_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@contextmanager
def db_session():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_db_connection():
    with db_session() as session:
        session.execute(text("SELECT 1"))
