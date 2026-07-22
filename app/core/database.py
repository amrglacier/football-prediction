"""Database engine, session management and declarative base."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


# SQLite doesn't support pool_size/max_overflow
if "sqlite" in settings.database_url:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.app_debug,
    )
else:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.app_debug,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """FastAPI dependency: yield an async DB session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables (for development / first run)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
