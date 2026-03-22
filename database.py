import aiosqlite
import json
import os
from datetime import datetime
from config import DB_PATH


async def init_db():
    # Создаём папку если её нет (Railway volume может не создать автоматически)
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                active      INTEGER DEFAULT 1,
                leagues     TEXT DEFAULT '[]',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                match_id    TEXT,
                match_name  TEXT,
                league      TEXT,
                signal_type TEXT,
                description TEXT,
                score       TEXT,
                set_num     INTEGER,
                sent_at     TEXT DEFAULT (datetime('now')),
                result      TEXT DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS matches_tracked (
                match_id        TEXT PRIMARY KEY,
                match_name      TEXT,
                league          TEXT,
                started_at      TEXT,
                last_score      TEXT,
                last_set        INTEGER DEFAULT 1,
                set_scores      TEXT DEFAULT '[]',
                consecutive_for TEXT DEFAULT '',
                consecutive_cnt INTEGER DEFAULT 0,
                tto_sent        TEXT DEFAULT '[]',
                pre_match_sent  INTEGER DEFAULT 0,
                finished        INTEGER DEFAULT 0
            );
        """)
        await db.commit()


# ─── Users ────────────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
        """, (user_id, username))
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE active=1") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def set_user_leagues(user_id: int, leagues: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET leagues=? WHERE user_id=?",
            (json.dumps(leagues), user_id)
        )
        await db.commit()


async def get_user_leagues(user_id: int) -> list[str]:
    user = await get_user(user_id)
    if not user or not user["leagues"]:
        return []
    return json.loads(user["leagues"])


# ─── Signals ──────────────────────────────────────────────────────────────────

async def save_signal(user_id: int, match_id: str, match_name: str,
                      league: str, signal_type: str, description: str,
                      score: str, set_num: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO signals
              (user_id, match_id, match_name, league, signal_type, description, score, set_num)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, match_id, match_name, league, signal_type, description, score, set_num))
        await db.commit()


async def get_signal_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT signal_type, COUNT(*) as cnt FROM signals WHERE user_id=? GROUP BY signal_type",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        total = sum(r[1] for r in rows)
        by_type = {r[0]: r[1] for r in rows}

        async with db.execute(
            "SELECT COUNT(*) FROM signals WHERE user_id=? AND DATE(sent_at)=DATE('now')",
            (user_id,)
        ) as cur:
            today = (await cur.fetchone())[0]

    return {"total": total, "by_type": by_type, "today": today}


async def get_recent_signals(user_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM signals WHERE user_id=?
            ORDER BY sent_at DESC LIMIT ?
        """, (user_id, limit)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ─── Match tracking ───────────────────────────────────────────────────────────

async def get_tracked_match(match_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM matches_tracked WHERE match_id=?", (match_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_tracked_match(match_id: str, match_name: str, league: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO matches_tracked (match_id, match_name, league, started_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(match_id) DO NOTHING
        """, (match_id, match_name, league, datetime.utcnow().isoformat()))
        await db.commit()


async def update_match_state(match_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [match_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE matches_tracked SET {sets} WHERE match_id=?", vals
        )
        await db.commit()


async def mark_match_finished(match_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE matches_tracked SET finished=1 WHERE match_id=?", (match_id,)
        )
        await db.commit()


async def get_active_tracked_matches() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM matches_tracked WHERE finished=0"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
