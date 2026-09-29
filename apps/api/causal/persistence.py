"""Anonymous reflection session persistence for production deployments."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

DatabasePool = AsyncConnectionPool[AsyncConnection[DictRow]]


class SessionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    MISSING = "missing"


class SessionRepository(Protocol):
    async def setup(self) -> None: ...

    async def create(self, thread_id: str) -> None: ...

    async def status(self, thread_id: str) -> SessionStatus: ...

    async def delete(self, thread_id: str) -> None: ...


class MemorySessionRepository:
    """Development repository with the same expiry behavior as production."""

    def __init__(self, ttl: timedelta) -> None:
        self._ttl = ttl
        self._expires_at: dict[str, datetime] = {}

    async def setup(self) -> None:
        return None

    async def create(self, thread_id: str) -> None:
        self._expires_at[thread_id] = datetime.now(UTC) + self._ttl

    async def status(self, thread_id: str) -> SessionStatus:
        expires_at = self._expires_at.get(thread_id)
        if expires_at is None:
            return SessionStatus.MISSING
        if expires_at <= datetime.now(UTC):
            self._expires_at.pop(thread_id, None)
            return SessionStatus.EXPIRED
        return SessionStatus.ACTIVE

    async def delete(self, thread_id: str) -> None:
        self._expires_at.pop(thread_id, None)


class PostgresSessionRepository:
    """Minimal session index layered beside LangGraph checkpoint tables."""

    def __init__(self, pool: DatabasePool, ttl: timedelta) -> None:
        self._pool = pool
        self._ttl = ttl

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS causal_sessions (
                    thread_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS causal_sessions_expires_at_idx
                ON causal_sessions (expires_at)
                """
            )

    async def create(self, thread_id: str) -> None:
        expires_at = datetime.now(UTC) + self._ttl
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO causal_sessions (thread_id, expires_at)
                VALUES (%s, %s)
                """,
                (thread_id, expires_at),
            )

    async def status(self, thread_id: str) -> SessionStatus:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT expires_at FROM causal_sessions WHERE thread_id = %s",
                (thread_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return SessionStatus.MISSING
            expires_at = row["expires_at"]
            if expires_at <= datetime.now(UTC):
                await connection.execute(
                    "DELETE FROM causal_sessions WHERE thread_id = %s",
                    (thread_id,),
                )
                return SessionStatus.EXPIRED
            return SessionStatus.ACTIVE

    async def delete(self, thread_id: str) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "DELETE FROM causal_sessions WHERE thread_id = %s",
                (thread_id,),
            )