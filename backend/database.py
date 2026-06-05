from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os
from dotenv import load_dotenv

load_dotenv()

_default_sqlite = f"sqlite+aiosqlite:///{Path(__file__).parent / 'talon.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _default_sqlite)

# Local dev without Postgres/Docker: fall back to SQLite if asyncpg isn't installed
if DATABASE_URL.startswith("postgresql") and os.getenv("TALON_FORCE_POSTGRES") != "1":
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        DATABASE_URL = _default_sqlite

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
