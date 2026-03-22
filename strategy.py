"""
Движок стратегии: генерирует сигналы по правилам из нашей стратегии.
Каждый вызов check_match() возвращает список новых сигналов (если есть).
"""

import json
from dataclasses import dataclass, field
from typing import Optional
from config import STRATEGY


@dataclass
class Signal:
    signal_type: str       # pre_match | tto_before | series | endgame | setball | tiebreak
    emoji: str
    title: str
    description: str
    score: str             # "12:10"
    set_num: int
    confidence: str        # 🟢 Высокая / 🟡 Средняя / 🔴 Низкая


# ─── Эмодзи и текст по типу ───────────────────────────────────────────────────

SIGNAL_META = {
    "pre_match":  ("📋", "Предматчевый анализ"),
    "tto_before": ("⏸", "Перед техническим тайм-аутом"),
    "series":     ("🔥", "Серия очков"),
    "endgame":    ("⚡", "Вход в концовку"),
    "setball":    ("🎯", "Сетбол"),
    "tiebreak":   ("🏆", "Тай-брейк (5-й сет)"),
}


def _score_str(h: int, a: int) -> str:
    return f"{h}:{a}"


def check_match(match: dict, prev_state: Optional[dict]) -> list[Signal]:
    """
    match      — текущее состояние матча из scraper
    prev_state — dict из базы (last_score, tto_sent, consecutive_for, consecutive_cnt)
    Возвращает список новых Signal для отправки.
    """
    signals: list[Signal] = []

    if match["status"] != "inprogress":
        return signals

    h = match["home_cur"]
    a = match["away_cur"]
    set_num = match["current_set"]
    score_str = _score_str(h, a)
    is_tiebreak = set_num == 5

    # Загружаем предыдущее состояние
    tto_sent: list[str] = json.loads(prev_state.get("tto_sent", "[]")) if prev_state else []
    cons_for: str = prev_state.get("consecutive_for", "") if prev_state else ""
    cons_cnt: int = int(prev_state.get("consecutive_cnt", 0)) if prev_state else 0
    last_score: str = prev_state.get("last_score", "") if prev_state else ""
    last_set: int = int(prev_state.get("last_set", 1)) if prev_state else 1

    # Новый сет — сбрасываем часть состояния
    if set_num != last_set:
        tto_sent = []
        cons_for = ""
        cons_cnt = 0

    max_score = STRATEGY["tiebreak_max"] if is_tiebreak else STRATEGY["max_score"]

    # ── 1. Перед техническим тайм-аутом (только обычные сеты) ────────────────
    if not is_tiebreak:
        for tto in STRATEGY["tto_scores"]:
            alert_at = tto - STRATEGY["tto_alert_offset"]  # 7 и 15
            key = f"set{set_num}_tto{tto}"
            if key not in tto_sent:
                leading = max(h, a)
                if leading == alert_at:
                    emoji, title = SIGNAL_META["tto_before"]
                    signals.append(Signal(
                        signal_type="tto_before",
                        emoji=emoji,
                        title=title,
                        description=(
                            f"Счёт {score_str} — до ТТО на {tto} осталось 1 очко.\n"
                            f"После ТТО подающая команда часто меняет вид подачи. "
                            f"Первые 1–2 очка после ТТО — высокая неопределённость."
                        ),
                        score=score_str,
                        set_num=set_num,
                        confidence="🟡 Средняя",
                    ))
                    tto_sent.append(key)

    # ── 2. Серия 3+ очков у одной команды ────────────────────────────────────
    if last_score and last_score != score_str and set_num == last_set:
        lh, la = (int(x) for x in last_score.split(":"))
        if h > lh:
            scored_team = "home"
        elif a > la:
            scored_team = "away"
        else:
            scored_team = ""

        if scored_team:
            if scored_team == cons_for:
                cons_cnt += 1
            else:
                cons_for = scored_team
                cons_cnt = 1

            if cons_cnt == STRATEGY["series_threshold"]:
                team_name = match["home"] if scored_team == "home" else match["away"]
                emoji, title = SIGNAL_META["series"]
                signals.append(Signal(
                    signal_type="series",
                    emoji=emoji,
                    title=title,
                    description=(
                        f"{team_name} выигрывает {cons_cnt} очка подряд! Счёт {score_str}.\n"
                        f"Серия может продолжиться — команда держит инициативу на подаче."
                    ),
                    score=score_str,
                    set_num=set_num,
                    confidence="🟢 Высокая",
                ))

    # ── 3. Вход в концовку ────────────────────────────────────────────────────
    if not is_tiebreak:
        endgame_start = STRATEGY["endgame_start"]
        endgame_key = f"set{set_num}_endgame"
        leading = max(h, a)
        if leading == endgame_start and endgame_key not in tto_sent:
            emoji, title = SIGNAL_META["endgame"]
            signals.append(Signal(
                signal_type="endgame",
                emoji=emoji,
                title=title,
                description=(
                    f"Счёт {score_str} — начинается концовка сета ({endgame_start}+).\n"
                    f"Ошибки на подаче растут (+40% к норме). Обе команды нервничают. "
                    f"Вероятна частая смена очков."
                ),
                score=score_str,
                set_num=set_num,
                confidence="🟢 Высокая",
            ))
            tto_sent.append(endgame_key)

    # ── 4. Сетбол ─────────────────────────────────────────────────────────────
    setball_score = STRATEGY["setball_score"] if not is_tiebreak else 14
    setball_key = f"set{set_num}_setball"
    if (h == setball_score or a == setball_score) and setball_key not in tto_sent:
        leader = match["home"] if h >= a else match["away"]
        emoji, title = SIGNAL_META["setball"]
        signals.append(Signal(
            signal_type="setball",
            emoji=emoji,
            title=title,
            description=(
                f"{leader} на сетболе! Счёт {score_str}.\n"
                f"Подающий переходит на безопасную подачу — вероятность эйса падает. "
                f"Ждите либо чистую атаку, либо ошибку под давлением."
            ),
            score=score_str,
            set_num=set_num,
            confidence="🟡 Средняя",
        ))
        tto_sent.append(setball_key)

    # ── 5. Тай-брейк ─────────────────────────────────────────────────────────
    tiebreak_key = "tiebreak_started"
    if is_tiebreak and tiebreak_key not in tto_sent:
        emoji, title = SIGNAL_META["tiebreak"]
        signals.append(Signal(
            signal_type="tiebreak",
            emoji=emoji,
            title=title,
            description=(
                f"Матч идёт в тай-брейк (5-й сет)! {score_str} по партиям.\n"
                f"15 очков до победы. Нервозность максимальная. Следите за каждой подачей."
            ),
            score=score_str,
            set_num=set_num,
            confidence="🟢 Высокая",
        ))
        tto_sent.append(tiebreak_key)

    # Возвращаем новое состояние вместе с сигналами
    new_state = {
        "last_score": score_str,
        "last_set": set_num,
        "tto_sent": json.dumps(tto_sent),
        "consecutive_for": cons_for,
        "consecutive_cnt": cons_cnt,
    }
    return signals, new_state


def format_signal_message(match: dict, signal: Signal) -> str:
    set_label = f"Тай-брейк" if signal.set_num == 5 else f"Партия {signal.set_num}"
    return (
        f"{signal.emoji} <b>{signal.title}</b>\n\n"
        f"🏐 <b>{match['match_name']}</b>\n"
        f"🏆 {match['league']}\n"
        f"📊 {set_label} • Счёт <b>{signal.score}</b>\n\n"
        f"{signal.description}\n\n"
        f"Уверенность: {signal.confidence}"
    )


def format_prematch_message(match: dict) -> str:
    start_str = match["start_dt"].strftime("%H:%M UTC") if match["start_dt"] else "скоро"
    league_lower = match["league"].lower()

    # Советы по лиге
    if "superliga" in league_lower or "serie a" in league_lower:
        league_tip = "🇮🇹 SuperLega/Serie A1 — высокая стабильность подачи. Серии длиннее, ошибок меньше."
    elif "plusliga" in league_lower:
        league_tip = "🇵🇱 PlusLiga — высокая дисперсия: много эйсов, много ошибок. Вход на непредсказуемость."
    elif "efeler" in league_lower:
        league_tip = "🇹🇷 Efeler — агрессивная подача. Высокий процент эйсов и ошибок."
    elif "vnl" in league_lower or "nations" in league_lower:
        league_tip = "🌍 VNL/Nations League — топ-сборные. Высокая стабильность в концовках."
    else:
        league_tip = "Следите за фазами: ТТО на 8 и 16, концовка с 18+."

    return (
        f"📋 <b>Предматчевый анализ</b>\n\n"
        f"🏐 <b>{match['match_name']}</b>\n"
        f"🏆 {match['league']}\n"
        f"🕐 Начало: <b>{start_str}</b>\n\n"
        f"{league_tip}\n\n"
        f"<b>Ключевые моменты для входа:</b>\n"
        f"• Счёт 7 или 15 — перед ТТО, смена вида подачи\n"
        f"• Счёт 18+ у лидера — концовка, растут ошибки\n"
        f"• Серия 3+ у одной команды — держать инициативу\n"
        f"• Сетбол (24:x) — безопасная подача, вход на смену очка"
    )
