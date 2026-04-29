# Deploy Guide - TON FlashBet

## Подготовка к деплою

### 1. Требования
- Аккаунт на [Render.com](https://render.com) (бесплатный)
- Токен Telegram бота от @BotFather
- Кошелек TON (например, TonKeeper)
- API ключ от [TON Center](https://toncenter.com) (бесплатный лимит: 1000 запросов/день)

### 2. Настройка бота в Telegram
1. Откройте @BotFather в Telegram
2. Выберите вашего бота → Bot Settings → Menu Button
3. Установите URL вашего TMA (после деплоя): `https://your-app.onrender.com/`
4. Включите TMA: Bot Settings → TON → Enable

### 3. Деплой на Render (бесплатно)

#### Вариант А: Автоматический деплой через render.yaml
1. Форкните/скопируйте этот репозиторий в свой GitHub
2. Зайдите на [Render.com](https://render.com)
3. New → Blueprint
4. Подключите GitHub репозиторий
5. Render автоматически создаст два сервиса:
   - `ton-flashbet-tma` (Flask TMA приложение)
   - `ton-flashbet-bot` (Telegram бот)

#### Вариант Б: Ручной деплой
1. New → Web Service
2. Подключите GitHub репозиторий
3. Настройки:
   - **Name**: ton-flashbet
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn tma:app` (для TMA) или `python bot.py` (для бота)

### 4. Environment Variables
В настройках сервиса на Render добавьте переменные окружения:

| Variable | Value | Description |
|----------|-------|-------------|
| `BOT_TOKEN` | ваш токен | Токен от @BotFather |
| `BOT_WALLET_ADDRESS` | адрес кошелька | TON кошелек для приема ставок |
| `TON_API_KEY` | ваш ключ | API ключ от TON Center |
| `BOT_USERNAME` | имя бота | Например: FlashBetTON_bot |
| `TMA_URL` | URL TMA | `https://your-app.onrender.com/` |
| `FLASK_SECRET` | случайная строка | Секретный ключ Flask |
| `DEBUG` | `false` | Отключить debug режим |

### 5. Установка webhook (для бота)
После деплоя установите webhook для Telegram бота:
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-bot-app.onrender.com/webhook"
```

Или используйте long polling (как сейчас в bot.py).

### 6. Проверка
1. Откройте TMA: `https://your-app.onrender.com/`
2. Проверьте работу бота: отправьте `/start`
3. Создайте тестовую ставку
4. Проверьте казну: `/treasury`

## Обновление (Deployment)
Render автоматически обновляет приложение при push в GitHub:
```bash
git add .
git commit -m "Update: description"
git push origin main
```

## Мониторинг
- Логи: Render Dashboard → Your Service → Logs
- Баланс кошелька: команда `/treasury` в боте
- База данных: файл `storage.json` (в бесплатном тарифе Render диск не персистентный!)

## Важно: База данных на бесплатном хостинге
⚠️ **Проблема**: Render Free удаляет файлы при перезапуске.

**Решения**:
1. **Использовать SQLite** (файл будет сохраняться между перезапусками в рамках одного деплоя)
2. **Подключить внешнее хранилище**:
   - Supabase (бесплатно до 500MB)
   - MongoDB Atlas (бесплатно до 512MB)
   - Redis Cloud (бесплатно)

Для быстрого старта можно использовать SQLite (см. `shared/db_sqlite.py`).

## Пример перехода на SQLite

```python
# shared/db_sqlite.py
import sqlite3
import json

def init_db():
    conn = sqlite3.connect('flashbet.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS data
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def load_db():
    init_db()
    conn = sqlite3.connect('flashbet.db')
    c = conn.cursor()
    c.execute("SELECT value FROM data WHERE key='main'")
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {"bets": {}, "users": {}, ...}
```

## Полезные ссылки
- [Render Python Guide](https://render.com/docs/deploy-python-flask)
- [TON Center API](https://toncenter.com/api/v2/)
- [CoinGecko API](https://www.coingecko.com/en/api/documentation)
- [Telegram WebApp Docs](https://core.telegram.org/bots/webapps)
