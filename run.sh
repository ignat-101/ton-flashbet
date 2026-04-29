#!/bin/bash
# Запускаем бота в фоновом режиме
python bot.py &

# Запускаем TMA (он будет слушать порт Render)
python tma.py
