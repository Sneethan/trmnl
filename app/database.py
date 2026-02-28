import json
import os
from datetime import datetime, timezone

import aiosqlite

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/trmnl.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    uuid TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    plugin_setting_id INTEGER,
    stop_id INTEGER DEFAULT 19843,
    station_name TEXT DEFAULT 'Melbourne Central',
    platform_numbers TEXT,
    refresh_minutes INTEGER DEFAULT 5,
    cached_departures TEXT,
    cache_updated_at TEXT,
    user_name TEXT,
    user_email TEXT,
    time_zone TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Migrations for existing databases that predate new columns.
_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN refresh_minutes INTEGER DEFAULT 5",
    "ALTER TABLE users ADD COLUMN cached_departures TEXT",
    "ALTER TABLE users ADD COLUMN cache_updated_at TEXT",
]


async def _get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await _get_db()
    try:
        await db.execute(_CREATE_TABLE)
        await db.commit()
        for sql in _MIGRATIONS:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception:
                pass  # Column already exists — safe to ignore
    finally:
        await db.close()


async def get_user(uuid: str) -> dict | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE uuid = ?", (uuid,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_user(
    uuid: str,
    access_token: str,
    plugin_setting_id: int | None = None,
    user_name: str | None = None,
    user_email: str | None = None,
    time_zone: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO users (uuid, access_token, plugin_setting_id,
               user_name, user_email, time_zone, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid, access_token, plugin_setting_id, user_name, user_email, time_zone, now, now),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_user(uuid)


async def update_user_token(
    uuid: str,
    access_token: str,
    plugin_setting_id: int | None = None,
) -> None:
    """Update access_token and plugin_setting_id for an existing user
    (e.g. after install/success webhook when user was auto-created by /manage)."""
    now = datetime.now(timezone.utc).isoformat()
    db = await _get_db()
    try:
        await db.execute(
            """UPDATE users SET access_token = ?, plugin_setting_id = ?, updated_at = ?
               WHERE uuid = ?""",
            (access_token, plugin_setting_id, now, uuid),
        )
        await db.commit()
    finally:
        await db.close()


async def update_user_settings(
    uuid: str,
    stop_id: int,
    station_name: str,
    platform_numbers: str | None = None,
    refresh_minutes: int = 5,
) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    db = await _get_db()
    try:
        await db.execute(
            """UPDATE users SET stop_id = ?, station_name = ?,
               platform_numbers = ?, refresh_minutes = ?, updated_at = ? WHERE uuid = ?""",
            (stop_id, station_name, platform_numbers, refresh_minutes, now, uuid),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_user(uuid)


async def set_cached_departures(uuid: str, data: dict) -> None:
    """Persist a fresh departure payload against the user so it can be reused
    within their chosen refresh window."""
    now = datetime.now(timezone.utc).isoformat()
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE users SET cached_departures = ?, cache_updated_at = ? WHERE uuid = ?",
            (json.dumps(data), now, uuid),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_user(uuid: str):
    db = await _get_db()
    try:
        await db.execute("DELETE FROM users WHERE uuid = ?", (uuid,))
        await db.commit()
    finally:
        await db.close()
