# 🏐 Volleyball Signal Bot

Telegram-бот, который отслеживает live-матчи по волейболу и отправляет торговые сигналы по стратегии «очко в сете».

---

## Как это работает

**Данные:** SofaScore публичный API (обновление каждые 30 секунд)

**Сигналы:**
| Тип | Когда | Суть |
|-----|-------|------|
| 📋 Предматчевый | За 15 мин до старта | Анализ лиги и ключевые моменты |
| ⏸ Перед ТТО | Счёт 7 или 15 | Смена тактики подачи после тайм-аута |
| 🔥 Серия | 3+ очка подряд | Команда держит инициативу |
| ⚡ Концовка | Лидер набирает 18 | Ошибки подачи растут +40% |
| 🎯 Сетбол | 24:x | Подающий уходит на безопасную подачу |
| 🏆 Тай-брейк | 5-й сет | Максимальная нервозность |

---

## Быстрый старт

### 1. Получи токен бота

1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Напиши `/newbot`
3. Задай имя и username боту
4. Скопируй токен вида `1234567890:ABC...XYZ`

### 2. Разверни на Railway (бесплатно)

**Railway** даёт $5 кредита в месяц — хватит на постоянную работу небольшого бота.

1. Зарегистрируйся на [railway.app](https://railway.app)

2. Нажми **"New Project" → "Deploy from GitHub repo"**

3. Форкни этот репозиторий или загрузи папку через GitHub

4. В настройках проекта Railway добавь переменные окружения:
   ```
   TELEGRAM_TOKEN = твой_токен_от_BotFather
   DB_PATH = /data/volleyball.db
   ```

5. Подключи **Volume** (для хранения базы):
   - Settings → Volumes → Add Volume
   - Mount path: `/data`

6. Railway автоматически найдёт `Dockerfile` и запустит бот

### 3. Альтернатива: локальный запуск

```bash
# Клонируй репозиторий
git clone <your-repo>
cd volleyball_bot

# Установи зависимости
pip install -r requirements.txt

# Создай .env файл
cp .env.example .env
# Открой .env и вставь свой TELEGRAM_TOKEN

# Запусти
python bot.py
```

---

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запустить бота |
| `/leagues` | Выбрать лиги для отслеживания |
| `/status` | Показать текущие live-матчи |
| `/history` | Последние 10 сигналов |
| `/stats` | Статистика по типам сигналов |
| `/help` | Описание всех сигналов |

---

## Настройка лиг

В `/leagues` можно выбрать конкретные лиги:

- 🇮🇹 SuperLega (мужчины)
- 🇮🇹 Serie A1 (женщины)
- 🇵🇱 PlusLiga
- 🇹🇷 Efeler Ligi
- 🇧🇷 Superliga Brasil
- 🇰🇷 V-League
- 🌍 CEV Champions League
- 🌍 VNL / Nations League

По умолчанию — все лиги.

---

## Структура проекта

```
volleyball_bot/
├── bot.py          # Telegram handlers, точка входа
├── scheduler.py    # Фоновый опрос и рассылка сигналов
├── strategy.py     # Логика генерации сигналов
├── scraper.py      # SofaScore API клиент
├── database.py     # SQLite (aiosqlite)
├── config.py       # Конфигурация и константы
├── requirements.txt
├── Dockerfile
├── railway.toml
└── .env.example
```

---

## Настройка стратегии

В `config.py` → `STRATEGY`:

```python
STRATEGY = {
    "tto_scores": [8, 16],     # При каком счёте ТТО
    "tto_alert_offset": 1,     # За сколько очков предупреждаем
    "endgame_start": 18,       # Начало концовки
    "setball_score": 24,       # Сетбол
    "series_threshold": 3,     # Минимальная серия для сигнала
}
```

Также в `config.py`:
```python
LIVE_POLL_INTERVAL = 30          # Секунды между опросами live
PRE_MATCH_ALERT_MINUTES = 15     # За сколько минут предматчевый сигнал
```

---

## Troubleshooting

**Бот не отвечает**
→ Проверь `TELEGRAM_TOKEN` в переменных окружения Railway

**Нет сигналов**
→ Проверь `/status` — возможно сейчас нет live-матчей по выбранным лигам

**SofaScore не отвечает**
→ Временная блокировка IP. На Railway обычно решается само через 5–10 минут.

**База данных сбрасывается при деплое**
→ Убедись что Volume подключён к `/data` и переменная `DB_PATH=/data/volleyball.db`
