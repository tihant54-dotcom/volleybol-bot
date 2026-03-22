import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

# Интервалы опроса (секунды)
LIVE_POLL_INTERVAL = 30       # как часто обновляем live-матчи
PRE_MATCH_ALERT_MINUTES = 15  # за сколько минут до матча шлём предматчевый сигнал

# Целевые лиги (ключевые слова в названии турнира)
DEFAULT_LEAGUES = [
    "superliga",
    "plusliga",
    "serie a1",
    "serie a",
    "efeler",
    "volleyball league",
    "cev champions",
    "vnl",
    "world league",
    "nations league",
]

# Пороги стратегии
STRATEGY = {
    "tto_scores": [8, 16],          # технические тайм-ауты
    "tto_alert_offset": 1,          # сигналим за 1 очко до ТТО (7, 15)
    "endgame_start": 18,            # начало концовки
    "setball_score": 24,            # сетбол
    "series_threshold": 3,          # серия X очков подряд → сигнал
    "max_score": 25,                # обычный максимум сета
    "tiebreak_max": 15,             # максимум тай-брейка
}

DB_PATH = os.getenv("DB_PATH", "volleyball.db")

SOFASCORE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}
SOFASCORE_BASE = "https://api.sofascore.com/api/v1"
