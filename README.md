# README.md - TON FlashBet

🎲 **TON FlashBet** — Децентрализованная платформа для ставок на базе Telegram WebApp и TON блокчейна.

## 🌟 Возможности

- 🎲 **Ставки peer-to-peer** — создавайте ставки с друзьями
- 💰 **Работа через TON** — прозрачные транзакции в блокчейне
- 📊 **Оракул цен** — отслеживание криптовалют в реальном времени
- 🏆 **Голосование со стейком** — честное разрешение споров
- 👥 **Реферальная система** — зарабатывайте приглашая друзей
- 🔒 **Безопасность** — проверка подписи Telegram, валидация данных
- ☁️ **Бесплатный хостинг** — готово к деплою на Render.com

## 🚀 Быстрый старт

### 1. Клонирование и установка

```bash
git clone <your-repo-url>
cd ton-flashbet
pip install -r requirements.txt
```

### 2. Настройка окружения

Создайте файл `.env` на основе `.env.production`:

```bash
cp .env.production .env
# Отредактируйте .env, заполнив значения
```

**Обязательные переменные:**
- `BOT_TOKEN` — токен от @BotFather
- `BOT_WALLET_ADDRESS` — ваш TON кошелек
- `TON_API_KEY` — ключ от TON Center (бесплатно: https://toncenter.com)

### 3. Запуск

**Telegram бот:**
```bash
python bot.py
```

**TMA (WebApp):**
```bash
python tma.py
# или через gunicorn:
gunicorn tma:app
```

### 4. Настройка бота

1. Откройте @BotFather в Telegram
2. Выберите вашего бота → Bot Settings → Menu Button
3. Установите URL: `https://your-domain.com/`
4. Включите WebApp: Bot Settings → TON → Enable

## 🧪 Тестирование

Запуск юнит-тестов:

```bash
pytest tests/ -v
```

## 📦 Деплой на Render.com (бесплатно)

См. подробную инструкцию в [DEPLOY.md](DEPLOY.md).

Быстрый деплой:

1. Залейте код на GitHub
2. Зайдите на [Render.com](https://render.com)
3. New → Blueprint → Подключите репозиторий
4. Render автоматически создаст два сервиса (бот + TMA)

## 🏗️ Структура проекта

```
ton-flashbet/
├── bot.py              # Telegram бот (long polling/webhook)
├── tma.py              # Flask TMA приложение
├── templates/
│   └── tma.html       # Интерфейс Telegram WebApp
├── shared/
│   ├── db.py          # Работа с БД (JSON с бэкапами)
│   └── ton.py         # TON и крипто API
├── tests/
│   └── test_basic.py  # Юнит-тесты
├── storage.json       # База данных (создается автоматически)
├── requirements.txt   # Python зависимости
├── render.yaml        # Конфигурация для Render
├── Procfile          # Для Heroku/Render
└── DEPLOY.md         # Инструкция по деплою
```

## 🔒 Безопасность

- ✅ Проверка подписи Telegram WebApp (initData)
- ✅ Валидация всех входных данных
- ✅ Защита от XSS (экранирование HTML)
- ✅ Rate limiting для API
- ✅ Блокировки при concurrent доступе к БД
- ✅ Автоматические бэкапы БД
- ⚠️ Для продакшена: переход на SQLite/PostgreSQL

## 💡 Как это работает

1. **Создание ставки:** Пользователь создает ставку через бота или TMA
2. **Принятие:** Оппонент принимает ставку и переводит TON
3. **Активная ставка:** Оба перевода подтверждены, ставка активна
4. **Завершение:** Участник заявляет о победе
5. **Голосование:** Сообщество голосует (замораживая 0.1 TON)
6. **Результат:** Победитель получает 2x сумму минус комиссия

## 📊 Комиссии и бонусы

- **Комиссия платформы:** 0.1 TON с каждой ставки
- **Бонус за правильный голос:** 0.05 TON
- **Реферальный бонус:** настраивается в коде

## 🛠️ Технологии

- **Backend:** Python, Flask, python-telegram-bot
- **Blockchain:** TON (The Open Network)
- **API:** TON Center, CoinGecko
- **Frontend:** Telegram WebApp SDK, HTML/CSS/JS
- **Database:** JSON (MVP), готово к миграции на SQLite

## 📝 Лицензия

MIT License

## 🤝 Вклад в проект

Пулл-реквесты приветствуются! Пожалуйста:
1. Форкните репозиторий
2. Создайте ветку для фичи (`git checkout -b feature/AmazingFeature`)
3. Зафиксируйте изменения (`git commit -m 'Add some AmazingFeature'`)
4. Запушьте ветку (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

## 📞 Поддержка

Если у вас возникли вопросы или проблемы:
- Создайте Issue в репозитории
- Напишите в Telegram: @your_support_bot

---

**⚡ Сделано с любовью к TON экосистеме**
