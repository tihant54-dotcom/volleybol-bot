"""
Telegram бот — волейбольный сигнальщик.
Команды: /start /leagues /status /history /stats /help
"""

import asyncio
import json
import logging
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

import database as db
import scraper
import scheduler
from config import TELEGRAM_TOKEN, DEFAULT_LEAGUES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

LEAGUE_OPTIONS = [
    ("🇮🇹 SuperLega", "superliga"),
    ("🇮🇹 Serie A1 (ж)", "serie a"),
    ("🇵🇱 PlusLiga", "plusliga"),
    ("🇹🇷 Efeler Ligi", "efeler"),
    ("🇧🇷 Superliga BR", "superliga brasileira"),
    ("🇰🇷 V-League", "v-league"),
    ("🌍 CEV Champions", "cev champions"),
    ("🌍 VNL", "vnl"),
    ("✅ Все лиги", "__all__"),
]


async def leagues_keyboard(user_id: int) -> InlineKeyboardMarkup:
    current = await db.get_user_leagues(user_id)
    rows = []
    for label, key in LEAGUE_OPTIONS:
        if key == "__all__":
            btn = InlineKeyboardButton("✅ Все лиги", callback_data="league:__all__")
        else:
            tick = "✅" if key in current else "⬜"
            btn = InlineKeyboardButton(f"{tick} {label}", callback_data=f"league:{key}")
        rows.append([btn])
    rows.append([InlineKeyboardButton("💾 Сохранить", callback_data="league:save")])
    return InlineKeyboardMarkup(rows)


# ─── Команды ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_user(user.id, user.username or user.first_name)
    await update.message.reply_html(
        f"🏐 <b>Volleyball Signal Bot</b>\n\n"
        f"Привет, {user.first_name}! Я отслеживаю волейбольные матчи в реальном времени "
        f"и шлю сигналы по нашей стратегии.\n\n"
        f"<b>Что умею:</b>\n"
        f"• 📋 Предматчевый анализ за 15 мин до старта\n"
        f"• ⏸ Сигнал перед техническими тайм-аутами (счёт 7, 15)\n"
        f"• 🔥 Серия 3+ очков у одной команды\n"
        f"• ⚡ Вход в концовку (18+)\n"
        f"• 🎯 Сетбол / тай-брейк\n\n"
        f"<b>Команды:</b>\n"
        f"/leagues — выбрать лиги для отслеживания\n"
        f"/status — текущие live-матчи\n"
        f"/history — последние 10 сигналов\n"
        f"/stats — моя статистика\n"
        f"/help — помощь\n\n"
        f"Начни с /leagues 👇"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "<b>Как работает бот</b>\n\n"
        "Каждые 30 секунд я запрашиваю live-данные с SofaScore и проверяю:\n\n"
        "<b>⏸ Перед ТТО</b> — счёт 7 или 15, подающая команда сменит тактику\n"
        "<b>🔥 Серия</b> — одна команда выигрывает 3 очка подряд\n"
        "<b>⚡ Концовка</b> — лидирующий достигает 18, растут ошибки на подаче\n"
        "<b>🎯 Сетбол</b> — подающий переходит на безопасную подачу\n"
        "<b>🏆 Тай-брейк</b> — матч уходит в 5-й сет\n\n"
        "Уверенность сигнала:\n"
        "🟢 Высокая — статистически устойчивая ситуация\n"
        "🟡 Средняя — вероятная, но требует контекста\n"
        "🔴 Низкая — осторожно, высокая неопределённость\n\n"
        "<b>Источник данных:</b> SofaScore (публичный API)"
    )


async def cmd_leagues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_user(user.id, user.username or user.first_name)
    kb = await leagues_keyboard(user.id)
    current = await db.get_user_leagues(user.id)
    if not current:
        note = "Сейчас отслеживаются <b>все лиги</b>."
    else:
        note = f"Выбрано лиг: <b>{len(current)}</b>"

    await update.message.reply_html(
        f"🏆 <b>Фильтр по лигам</b>\n\n{note}\n\nВыбери лиги для получения сигналов:",
        reply_markup=kb,
    )


async def cb_league(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data.replace("league:", "")

    if data == "save":
        current = await db.get_user_leagues(user_id)
        if not current:
            text = "✅ Сохранено: отслеживаю <b>все лиги</b>"
        else:
            text = f"✅ Сохранено: {len(current)} лиг"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
        return

    current = await db.get_user_leagues(user_id)

    if data == "__all__":
        await db.set_user_leagues(user_id, [])
    elif data in current:
        current.remove(data)
        await db.set_user_leagues(user_id, current)
    else:
        current.append(data)
        await db.set_user_leagues(user_id, current)

    kb = await leagues_keyboard(user_id)
    try:
        await query.edit_message_reply_markup(reply_markup=kb)
    except Exception:
        pass


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("🔄 Запрашиваю live-матчи...")

    user = await db.get_user(user_id)
    user_leagues = json.loads(user.get("leagues", "[]") or "[]") if user else []
    if not user_leagues:
        user_leagues = DEFAULT_LEAGUES

    live = await scraper.get_live_matches()
    filtered = [m for m in live if scraper.matches_league_filter(m, user_leagues)]

    if not filtered:
        await update.message.reply_html(
            "📭 Сейчас нет live-матчей по вашим лигам.\n"
            "Используй /leagues чтобы расширить фильтр."
        )
        return

    lines = [f"📡 <b>Live-матчи ({len(filtered)})</b>\n"]
    for m in filtered[:10]:
        sets_str = " | ".join(f"{h}:{a}" for h, a in m["set_scores"])
        cur_score = f"{m['home_cur']}:{m['away_cur']}"
        lines.append(
            f"🏐 <b>{m['match_name']}</b>\n"
            f"   {m['league']}\n"
            f"   Партия {m['current_set']} • Счёт <b>{cur_score}</b>"
            + (f"\n   Партии: {sets_str}" if sets_str else "")
        )
    await update.message.reply_html("\n\n".join(lines))


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    signals = await db.get_recent_signals(user_id, limit=10)

    if not signals:
        await update.message.reply_text("📭 Сигналов пока не было. Жди live-матчей!")
        return

    TYPE_EMOJI = {
        "pre_match": "📋", "tto_before": "⏸", "series": "🔥",
        "endgame": "⚡", "setball": "🎯", "tiebreak": "🏆",
    }
    lines = ["📜 <b>Последние сигналы</b>\n"]
    for s in signals:
        em = TYPE_EMOJI.get(s["signal_type"], "📌")
        dt = s["sent_at"][:16].replace("T", " ")
        lines.append(
            f"{em} <b>{s['match_name']}</b>\n"
            f"   {s['league']} • Счёт {s['score']} • {dt}"
        )
    await update.message.reply_html("\n\n".join(lines))


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = await db.get_signal_stats(user_id)

    TYPE_LABEL = {
        "pre_match": "Предматчевые",
        "tto_before": "Перед ТТО",
        "series": "Серии",
        "endgame": "Концовки",
        "setball": "Сетболы",
        "tiebreak": "Тай-брейки",
    }
    by_type_lines = "\n".join(
        f"  • {TYPE_LABEL.get(k, k)}: {v}"
        for k, v in stats["by_type"].items()
    )

    await update.message.reply_html(
        f"📊 <b>Моя статистика</b>\n\n"
        f"Всего сигналов: <b>{stats['total']}</b>\n"
        f"Сегодня: <b>{stats['today']}</b>\n\n"
        f"По типам:\n{by_type_lines or '  пока нет данных'}"
    )


async def unknown_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Неизвестная команда. Используй /help")


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def post_init(app: Application):
    try:
        await db.init_db()
        log.info("Database initialized")
    except Exception as e:
        log.error("DB init failed: %s", e, exc_info=True)
        raise

    try:
        await app.bot.set_my_commands([
            BotCommand("start",   "Запустить бота"),
            BotCommand("leagues", "Выбрать лиги"),
            BotCommand("status",  "Live-матчи сейчас"),
            BotCommand("history", "История сигналов"),
            BotCommand("stats",   "Моя статистика"),
            BotCommand("help",    "Помощь"),
        ])
    except Exception as e:
        log.warning("Could not set commands: %s", e)

    log.info("Bot initialized, starting scheduler...")
    asyncio.create_task(scheduler.scheduler_loop(app.bot))


async def post_shutdown(app: Application):
    scheduler.stop_scheduler()
    await scraper.close_session()


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("leagues", cmd_leagues))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CallbackQueryHandler(cb_league, pattern="^league:"))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))

    log.info("Starting bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
