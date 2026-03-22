"""
Фоновый планировщик: опрашивает live-матчи и рассылает сигналы пользователям.
"""

import asyncio
import logging
from datetime import datetime

from telegram import Bot
from telegram.error import TelegramError

import database as db
import scraper
from strategy import check_match, format_signal_message, format_prematch_message
from config import (
    LIVE_POLL_INTERVAL,
    PRE_MATCH_ALERT_MINUTES,
    DEFAULT_LEAGUES,
)

log = logging.getLogger(__name__)

_running = False


async def _send_safe(bot: Bot, user_id: int, text: str):
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramError as e:
        log.warning("Cannot send to %d: %s", user_id, e)


async def _get_user_leagues(user: dict) -> list[str]:
    import json
    leagues = json.loads(user.get("leagues", "[]") or "[]")
    return leagues if leagues else DEFAULT_LEAGUES


async def process_live_matches(bot: Bot):
    """Основной цикл: проверяем live-матчи и шлём сигналы."""
    live_matches = await scraper.get_live_matches()
    if not live_matches:
        return

    users = await db.get_all_active_users()
    if not users:
        return

    for match in live_matches:
        mid = match["id"]

        # Убеждаемся, что матч в треккере
        await db.upsert_tracked_match(mid, match["match_name"], match["league"])
        prev_state = await db.get_tracked_match(mid)

        # Генерируем сигналы
        signals, new_state = check_match(match, prev_state)

        # Обновляем состояние матча в базе
        await db.update_match_state(mid, **new_state)

        if not signals:
            continue

        # Рассылаем каждому подходящему пользователю
        for user in users:
            user_leagues = await _get_user_leagues(user)
            if not scraper.matches_league_filter(match, user_leagues):
                continue

            for sig in signals:
                text = format_signal_message(match, sig)
                await _send_safe(bot, user["user_id"], text)
                await db.save_signal(
                    user_id=user["user_id"],
                    match_id=mid,
                    match_name=match["match_name"],
                    league=match["league"],
                    signal_type=sig.signal_type,
                    description=sig.description,
                    score=sig.score,
                    set_num=sig.set_num,
                )
                await asyncio.sleep(0.05)  # не спамим Telegram API


async def process_upcoming_matches(bot: Bot):
    """Рассылает предматчевые сигналы за PRE_MATCH_ALERT_MINUTES минут до начала."""
    users = await db.get_all_active_users()
    if not users:
        return

    # Собираем все нужные лиги
    all_leagues: set[str] = set(DEFAULT_LEAGUES)
    for user in users:
        for kw in await _get_user_leagues(user):
            all_leagues.add(kw)

    upcoming = await scraper.get_upcoming_matches(
        list(all_leagues),
        minutes_ahead=PRE_MATCH_ALERT_MINUTES,
    )

    for match in upcoming:
        mid = match["id"]
        prev = await db.get_tracked_match(mid)

        # Уже отправляли предматчевый?
        if prev and prev.get("pre_match_sent"):
            continue

        await db.upsert_tracked_match(mid, match["match_name"], match["league"])

        for user in users:
            user_leagues = await _get_user_leagues(user)
            if not scraper.matches_league_filter(match, user_leagues):
                continue

            text = format_prematch_message(match)
            await _send_safe(bot, user["user_id"], text)
            await db.save_signal(
                user_id=user["user_id"],
                match_id=mid,
                match_name=match["match_name"],
                league=match["league"],
                signal_type="pre_match",
                description="Предматчевый анализ",
                score="—",
                set_num=0,
            )

        await db.update_match_state(mid, pre_match_sent=1)


async def cleanup_finished(bot: Bot):
    """Помечает завершённые матчи как finished."""
    tracked = await db.get_active_tracked_matches()
    if not tracked:
        return

    live_ids = {m["id"] for m in (await scraper.get_live_matches())}
    for t in tracked:
        if t["match_id"] not in live_ids:
            # Матч больше не в live — завершён или ещё не начался
            detail = await scraper.get_match_detail(t["match_id"])
            if detail and detail["status"] == "finished":
                await db.mark_match_finished(t["match_id"])


async def scheduler_loop(bot: Bot):
    global _running
    _running = True
    log.info("Scheduler started")

    tick = 0
    while _running:
        try:
            await process_live_matches(bot)

            # Предматчевые и cleanup — каждые ~5 минут
            if tick % 10 == 0:
                await process_upcoming_matches(bot)
            if tick % 20 == 0:
                await cleanup_finished(bot)

        except Exception as e:
            log.error("Scheduler error: %s", e, exc_info=True)

        tick += 1
        await asyncio.sleep(LIVE_POLL_INTERVAL)


def stop_scheduler():
    global _running
    _running = False
