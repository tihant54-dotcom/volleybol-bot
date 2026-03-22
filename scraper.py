"""
Scraper: SofaScore public API  (volleyball live + scheduled)
FlashScore слишком агрессивно защищён от парсинга без Selenium;
SofaScore имеет открытый JSON API — данные те же самые.
"""

import aiohttp
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional
from config import SOFASCORE_HEADERS, SOFASCORE_BASE, DEFAULT_LEAGUES
import logging

log = logging.getLogger(__name__)

# Небольшой кэш чтобы не долбиться к API
_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(ssl=False, limit=10)
        _session = aiohttp.ClientSession(
            headers=SOFASCORE_HEADERS,
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15),
        )
    return _session


async def _get(url: str) -> Optional[dict]:
    session = await get_session()
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            log.warning("SofaScore %s → %d", url, resp.status)
    except Exception as e:
        log.error("SofaScore request error: %s", e)
    return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_match(event: dict) -> Optional[dict]:
    """Нормализует событие SofaScore в удобный dict."""
    try:
        home = event["homeTeam"]["name"]
        away = event["awayTeam"]["name"]
        tid  = str(event["id"])
        tournament = event.get("tournament", {}).get("name", "")
        category   = event.get("tournament", {}).get("category", {}).get("name", "")
        status     = event.get("status", {}).get("type", "unknown")  # notstarted / inprogress / finished

        # Счёт по партиям (sets)
        home_score = event.get("homeScore", {})
        away_score = event.get("awayScore", {})

        # Текущий счёт в текущей партии
        home_cur = home_score.get("current", 0)
        away_cur = away_score.get("current", 0)

        # Количество выигранных партий
        home_sets = home_score.get("normaltime", 0)
        away_sets = away_score.get("normaltime", 0)

        # Все партии: period1..period5
        set_scores = []
        for i in range(1, 6):
            k = f"period{i}"
            h = home_score.get(k)
            a = away_score.get(k)
            if h is not None and a is not None:
                set_scores.append((h, a))

        start_ts = event.get("startTimestamp", 0)
        start_dt = datetime.utcfromtimestamp(start_ts) if start_ts else None

        return {
            "id": tid,
            "home": home,
            "away": away,
            "match_name": f"{home} – {away}",
            "league": tournament,
            "category": category,
            "status": status,
            "home_cur": home_cur,
            "away_cur": away_cur,
            "home_sets": home_sets,
            "away_sets": away_sets,
            "set_scores": set_scores,
            "current_set": len(set_scores) + (1 if status == "inprogress" else 0),
            "start_dt": start_dt,
            "raw": event,
        }
    except Exception as e:
        log.debug("parse error: %s", e)
        return None


def matches_league_filter(match: dict, leagues: list[str]) -> bool:
    """Проверяет, входит ли матч в список лиг пользователя."""
    name = (match["league"] + " " + match["category"]).lower()
    return any(kw.lower() in name for kw in leagues)


# ─── API calls ────────────────────────────────────────────────────────────────

async def get_live_matches() -> list[dict]:
    data = await _get(f"{SOFASCORE_BASE}/sport/volleyball/events/live")
    if not data:
        return []
    events = data.get("events", [])
    result = []
    for e in events:
        m = _parse_match(e)
        if m:
            result.append(m)
    return result


async def get_scheduled_matches(days_ahead: int = 1) -> list[dict]:
    """Матчи на сегодня и следующие days_ahead дней."""
    result = []
    for delta in range(days_ahead + 1):
        d = (date.today() + timedelta(days=delta)).isoformat()
        data = await _get(f"{SOFASCORE_BASE}/sport/volleyball/scheduled-events/{d}")
        if not data:
            continue
        for e in data.get("events", []):
            m = _parse_match(e)
            if m:
                result.append(m)
    return result


async def get_match_detail(match_id: str) -> Optional[dict]:
    data = await _get(f"{SOFASCORE_BASE}/event/{match_id}")
    if not data:
        return None
    event = data.get("event")
    return _parse_match(event) if event else None


async def get_upcoming_matches(user_leagues: list[str],
                               minutes_ahead: int = 15) -> list[dict]:
    """Матчи, которые начнутся в ближайшие minutes_ahead минут."""
    scheduled = await get_scheduled_matches(days_ahead=0)
    now = datetime.utcnow()
    result = []
    for m in scheduled:
        if m["status"] != "notstarted":
            continue
        if not m["start_dt"]:
            continue
        delta = (m["start_dt"] - now).total_seconds() / 60
        if 0 < delta <= minutes_ahead:
            if not user_leagues or matches_league_filter(m, user_leagues):
                result.append(m)
    return result


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
