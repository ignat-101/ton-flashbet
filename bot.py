import os
import json
import time
import random
import requests
import sys
import logging
import hashlib
import hmac
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError, NetworkError, BadRequest

load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
TON_API = os.getenv('TON_API_ENDPOINT', 'https://toncenter.com/api/v2/jsonRPC')
BOT_WALLET = os.getenv('BOT_WALLET_ADDRESS')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'FlashBetTON_bot')
TMA_URL = os.getenv('TMA_URL', 'https://ваш-домен.vercel.app/')

# Подключаем общие модули
sys_path = os.path.dirname(os.path.dirname(__file__))
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from shared.db import (
    load_db, save_db, get_user, update_user, get_bet, save_bet, 
    get_treasury, update_treasury, add_treasury_transaction,
    get_referral_info, save_referral_info,
    validate_user_id, validate_amount
)
from shared.ton import verify_ton_transaction, get_ton_balance

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start с поддержкой реферальных ссылок и защитой от накрутки"""
    user = update.effective_user
    args = context.args
    
    # Валидация пользователя
    if not user or not user.id:
        logger.error("Invalid user in /start")
        return
    
    # Если есть реферальный код
    if args and args[0].startswith('REF'):
        ref_code = args[0]
        logger.info(f"User {user.id} joined with ref code: {ref_code}")
        
        try:
            # Находим пользователя с таким кодом
            db = load_db()
            referrer_id = None
            for uid, ref_info in db.get('referrals', {}).items():
                if ref_info.get('code') == ref_code:
                    referrer_id = uid
                    break
            
            if referrer_id:
                referrer_id_int = int(referrer_id)
                
                # Проверки безопасности
                if user.id == referrer_id_int:
                    await update.message.reply_text("❌ Нельзя участвовать в своей реферальной ссылке!")
                    logger.warning(f"User {user.id} tried to use own ref link")
                elif get_referral_info(user.id).get('referred_by'):
                    await update.message.reply_text("ℹ️ Вы уже зарегистрированы по реферальной ссылке.")
                else:
                    # Проверка на мультиаккаунт (простая эвристика)
                    referrer_data = get_user(referrer_id_int)
                    new_user_data = get_user(user.id, user.username or "")
                    
                    # Если реферер пытается накрутить сам себя (проверка по времени создания)
                    time_diff = abs(new_user_data.get('created_at', 0) - referrer_data.get('created_at', 0))
                    if time_diff < 60:  # Аккаунты созданы в течение минуты
                        logger.warning(f"Possible self-referral: {user.id} by {referrer_id}")
                        await update.message.reply_text("⚠️ Подозрительная активность. Реферал не засчитан.")
                    else:
                        # Записываем реферала
                        user_ref_info = get_referral_info(user.id)
                        user_ref_info['referred_by'] = referrer_id_int
                        save_referral_info(user.id, user_ref_info)
                        
                        # Обновляем счетчик реферера
                        referrer_ref_info = get_referral_info(referrer_id_int)
                        if user.id not in referrer_ref_info.get('referrals', []):
                            referrer_ref_info.setdefault('referrals', []).append(user.id)
                            referrer_ref_info['referrals_count'] = len(referrer_ref_info['referrals'])
                            save_referral_info(referrer_id_int, referrer_ref_info)
                            
                            try:
                                # Уведомляем реферера
                                await context.bot.send_message(
                                    chat_id=referrer_id_int,
                                    text=f"🎉 Новый реферал присоединился по вашей ссылке!"
                                )
                            except Exception as e:
                                logger.warning(f"Could not notify referrer {referrer_id_int}: {e}")
                            
                            await update.message.reply_text(
                                f"🎉 Вы присоединились по реферальной ссылке! Ваш реферер получит бонус."
                            )
                            logger.info(f"New referral: {user.id} referred by {referrer_id}")
        except Exception as e:
            logger.error(f"Error processing referral: {e}")
            await update.message.reply_text("❌ Ошибка обработки реферальной ссылки.")
    
    # Получаем/создаем пользователя
    get_user(user.id, user.username or "")
    
    # Основное приветствие
    keyboard = [
        [InlineKeyboardButton("🎲 Открыть TMA", web_app={"url": TMA_URL})],
        [InlineKeyboardButton("📋 Список команд", callback_data="show_commands")]
    ]
    
    await update.message.reply_text(
        "🎲 TON FlashBet — Непотопляемые ставки!\n\n"
        "🔥 Теперь с удобным интерфейсом в TMA!\n"
        "👥 Реферальная система: приглашай друзей и получай бонусы.\n"
        "🏆 Правильные решения в голосовании приносят +0.05 TON.\n"
        "💰 Казна проекта полностью прозрачна.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список команд"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📋 Команды бота:\n\n"
        "/start — Перезапуск бота\n"
        "/app — Открыть TMA\n"
        "/mybets — Мои ставки (текстовый режим)\n"
        "/referral — Реферальная ссылка\n"
        "/treasury — Баланс казны\n\n"
        "Для полноценной работы рекомендуем использовать TMA!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")
        ]])
    )

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)

async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /app для открытия TMA"""
    keyboard = [[
        InlineKeyboardButton("🎲 Открыть TMA", web_app={"url": TMA_URL})
    ]]
    await update.message.reply_text(
        "Откройте TON FlashBet в Telegram:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /referral для генерации реферальной ссылки"""
    user_id = update.effective_user.id
    ref_info = get_referral_info(user_id)
    
    if not ref_info.get('code'):
        # Генерируем код
        code = f"REF{user_id}{random.randint(1000, 9999)}"
        ref_info['code'] = code
        save_referral_info(user_id, ref_info)
        logger.info(f"Generated referral code for user {user_id}: {code}")
    
    referral_link = f"https://t.me/{BOT_USERNAME}?start={ref_info['code']}"
    
    await update.message.reply_text(
        "👥 Ваша реферальная ссылка:\n\n"
        f"`{referral_link}`\n\n"
        "📊 Статистика:\n"
        f"Приглашено пользователей: {len(ref_info.get('referrals', []))}\n"
        f"Заработано на рефералах: {ref_info.get('earnings', 0)} TON\n\n"
        "💡 Бонус рефереру начисляется, когда приглашенный участвует в ставках.",
        parse_mode='Markdown'
    )

async def treasury_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /treasury для просмотра казны"""
    treasury = get_treasury()
    
    # Получаем реальный баланс кошелька
    real_balance = get_ton_balance(BOT_WALLET) if BOT_WALLET else 0
    
    # Последние транзакции
    recent_tx = treasury.get('transactions', [])[-5:]
    tx_text = "\n".join([
        f"• {tx['type']}: {tx['amount']:.2f} TON — {tx['description']}"
        for tx in recent_tx
    ]) if recent_tx else "Пока нет транзакций"
    
    await update.message.reply_text(
        "💰 Казна TON FlashBet\n\n"
        f"Баланс в системе: {treasury.get('balance', 0):.2f} TON\n"
        f"Реальный баланс кошелька: {real_balance:.2f} TON\n"
        f"Адрес: `{BOT_WALLET}`\n\n"
        "📜 Последние транзакции:\n"
        f"{tx_text}\n\n"
        "🔍 Все транзакции прозрачны и доступны в TMA.",
        parse_mode='Markdown'
    )

async def new_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Пример: /newbet @friend 1.0 'BTC > 100k'")
        return
    
    try:
        amount_str = args[1]
        condition = ' '.join(args[2:])
        opponent_tag = args[0].replace('@', '')
        
        # Валидация суммы
        if not validate_amount(amount_str, min_amount=0.1, max_amount=1000):
            await update.message.reply_text("❌ Некорректная сумма ставки (0.1 - 1000 TON)")
            return
        
        amount = float(amount_str)
        
        # Валидация условия
        if len(condition) > 500:
            await update.message.reply_text("❌ Условие слишком длинное (макс 500 символов)")
            return
        
        bet_id = f"bet_{int(time.time())}"
        user = get_user(update.effective_user.id, update.effective_user.username or "")
        
        bet_data = {
            'id': bet_id,
            'initiator': update.effective_user.id,
            'opponent_tag': opponent_tag[:50],  # Limit length
            'amount': amount,
            'condition': condition,
            'status': 'pending',
            'winner': None,
            'created_at': time.time(),
            'votes_detail': {},
            'total_weight_initiator': 0.0,
            'total_weight_opponent': 0.0,
            'voters': [],
            'voting_stakes_locked': {},
            'stake_returned': {},
            'auditors': [],
            'auditor_votes': {},
            'suspect_voters': []
        }
        
        if not save_bet(bet_data):
            await update.message.reply_text("❌ Ошибка сохранения ставки")
            return
        
        logger.info(f"New bet created: {bet_id} by user {update.effective_user.id}")
        
        keyboard = [[
            InlineKeyboardButton("✅ Принять", callback_data=f"accept_{bet_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{bet_id}")
        ]]
        
        await update.message.reply_text(
            f"🔥 НОВАЯ СТАВКА!\n\n"
            f"📋 Условие: {condition}\n"
            f"💰 Сумма: {amount} TON\n"
            f"👤 От: @{update.effective_user.username}\n\n"
            f"Для принятия отправьте {amount} TON на:\n`{BOT_WALLET}`\n"
            f"С комментарием: `{bet_id}`",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except ValueError:
        await update.message.reply_text("❌ Некорректная сумма ставки")
    except Exception as e:
        logger.error(f"Error in new_bet: {e}")
        await update.message.reply_text(f"Ошибка: {e}")

async def accept_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bet_id = query.data.split('_')[1]
    
    bet = get_bet(bet_id)
    if not bet:
        await query.edit_message_text("❌ Ставка не найдена.")
        return
    
    user_id = query.from_user.id
    
    # Проверяем, что это не инициатор
    if user_id == bet['initiator']:
        await query.answer("Вы не можете принять свою ставку!")
        return
    
    bet['status'] = 'awaiting_payment'
    bet['opponent'] = user_id
    save_bet(bet)
    
    logger.info(f"Bet {bet_id} accepted by user {user_id}")
    
    await query.edit_message_text(
        f"✅ Ставка принята!\n\n"
        f"💳 Отправьте {bet['amount']} TON на адрес:\n`{BOT_WALLET}`\n"
        f"💡 В комментарии укажите: `{bet_id}`\n\n"
        f"После оплаты: `/pay {bet_id} <hash_транзакции>`",
        parse_mode='Markdown'
    )

async def pay_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Пример: /pay bet_12345 <hash>")
        return
    
    bet_id = args[0]
    tx_hash = args[1]
    
    bet = get_bet(bet_id)
    if not bet:
        await update.message.reply_text("Ставка не найдена.")
        return
    
    user_id = update.effective_user.id
    
    # Проверяем, что пользователь участник
    if user_id not in [bet['initiator'], bet.get('opponent')]:
        await update.message.reply_text("❌ Вы не участник этой ставки.")
        return
    
    # Проверяем транзакцию
    verification = verify_ton_transaction(tx_hash, bet['amount'], BOT_WALLET)
    
    if verification['valid']:
        if user_id == bet['initiator']:
            bet['initiator_paid'] = True
            logger.info(f"Initiator {user_id} paid for bet {bet_id}")
        elif user_id == bet.get('opponent'):
            bet['opponent_paid'] = True
            logger.info(f"Opponent {user_id} paid for bet {bet_id}")
        
        if bet.get('initiator_paid') and bet.get('opponent_paid'):
            bet['status'] = 'active'
            save_bet(bet)
            await update.message.reply_text(
                f"🎲 Ставка АКТИВНА!\n\n"
                f"Условие: {bet['condition']}\n"
                f"Ждем результата... Победитель получает {bet['amount']*2 - 0.1} TON"
            )
        else:
            save_bet(bet)
            await update.message.reply_text("✅ Оплата получена. Ждем второго участника.")
    else:
        await update.message.reply_text(f"❌ Транзакция не найдена или сумма неверна.\nОшибка: {verification.get('error', 'Unknown')}")

async def claim_win(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Пример: /won bet_12345")
        return
    
    bet_id = args[0]
    bet = get_bet(bet_id)
    
    if not bet:
        await update.message.reply_text("Ставка не найдена.")
        return
    
    user_id = update.effective_user.id
    
    if user_id not in [bet['initiator'], bet.get('opponent')]:
        await update.message.reply_text("❌ Вы не участник ставки.")
        return
    
    bet['status'] = 'claim_pending'
    bet['claimed_winner'] = user_id
    save_bet(bet)
    
    logger.info(f"Win claim for bet {bet_id} by user {user_id}")
    
    # Предлагаем голосование
    keyboard = [[
        InlineKeyboardButton("🏆 Подтвердить победу", callback_data=f"vouch_{bet_id}"),
        InlineKeyboardButton("⚠️ Оспорить!", callback_data=f"dispute_{bet_id}")
    ]]
    
    await update.message.reply_text(
        f"🏆 Заявление о победе в ставке!\n\n"
        f"Ставка: {bet['condition']}\n\n"
        f"⚠️ Для подтверждения победы нужно:\n"
        f"1. Заморозить 0.1 TON (вернется если вы в большинстве)\n"
        f"2. Ваш голос имеет вес: {get_user(user_id).get('reputation', 100)}\n"
        f"💡 Правильный голос принесет бонус 0.05 TON!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def vouch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for users who vouch for the winner (Stake-to-Vote) with bonus"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith('vouch_'):
        bet_id = data.split('_')[1]
        bet = get_bet(bet_id)
        
        if not bet:
            await query.answer("Ставка не найдена")
            return
        
        user_id = query.from_user.id
        
        # Check if already voted
        if user_id in bet['voters']:
            await query.answer("Вы уже голосовали!")
            return
        
        # Check if participant (can't vote)
        if user_id in [bet['initiator'], bet.get('opponent')]:
            await query.answer("Участники не голосуют!")
            return
        
        # Stake 0.1 TON (in real implementation, check TON transaction)
        # For MVP: assume stake is locked
        bet['voting_stakes_locked'][str(user_id)] = 0.1
        
        # Calculate vote weight
        user_data = get_user(user_id, query.from_user.username or "")
        weight = user_data.get('reputation', 100) / 100.0
        weight *= max(1.0, user_data.get('account_age_days', 365) / 365.0)
        weight *= max(1.0, user_data.get('mutual_groups', 5) / 5.0)
        
        # Determine choice (assuming claimant is winner)
        choice = 'initiator' if bet.get('claimed_winner') == bet['initiator'] else 'opponent'
        
        bet['votes_detail'][str(user_id)] = {'choice': choice, 'weight': weight, 'stake': 0.1}
        bet['voters'].append(user_id)
        
        if choice == 'initiator':
            bet['total_weight_initiator'] += weight
        else:
            bet['total_weight_opponent'] += weight
        
        save_bet(bet)
        logger.info(f"User {user_id} voted for {choice} in bet {bet_id}")
        
        await query.edit_message_text(
            f"✅ Ваш голос учтен!\n"
            f"Вес голоса: {weight:.2f}\n"
            f"Стейк: 0.1 TON заморожен\n\n"
            f"Текущий счет:\n"
            f"За инициатора: {bet['total_weight_initiator']:.2f}\n"
            f"За оппонента: {bet['total_weight_opponent']:.2f}\n\n"
            f"💡 Если вы правы, получите бонус 0.05 TON!"
        )

async def dispute_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for disputes — triggers Random Auditors"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith('dispute_'):
        bet_id = data.split('_')[1]
        bet = get_bet(bet_id)
        
        if not bet:
            await query.answer("Ставка не найдена")
            return
        
        bet['status'] = 'disputed'
        
        # Select 3 random auditors from user base (not participants)
        db = load_db()
        all_users = [int(uid) for uid in db['users'].keys()]
        potential_auditors = [u for u in all_users if u not in [bet['initiator'], bet.get('opponent')]]
        
        if len(potential_auditors) >= 3:
            auditors = random.sample(potential_auditors, 3)
            bet['auditors'] = auditors
            save_bet(bet)
            
            logger.info(f"Dispute for bet {bet_id}, auditors: {auditors}")
            
            await query.edit_message_text(
                f"⚖️ СПОР! Случайные аудиторы выбраны: {', '.join(map(str, auditors))}\n\n"
                f"Они решат исход ставки: {bet['condition']}"
            )
        else:
            save_bet(bet)
            await query.edit_message_text("⚖️ Спор! Недостаточно пользователей для аудита.")
        
        logger.info(f"Dispute opened for bet {bet_id}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("app", app_command))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("treasury", treasury_command))
    app.add_handler(CommandHandler("newbet", new_bet))
    app.add_handler(CommandHandler("pay", pay_bet))
    app.add_handler(CommandHandler("won", claim_win))
    app.add_handler(CallbackQueryHandler(accept_bet, pattern="^accept_"))
    app.add_handler(CallbackQueryHandler(vouch_handler, pattern="^vouch_"))
    app.add_handler(CallbackQueryHandler(dispute_handler, pattern="^dispute_"))
    app.add_handler(CallbackQueryHandler(show_commands, pattern="^show_commands"))
    app.add_handler(CallbackQueryHandler(back_to_start, pattern="^back_to_start"))
    
    logger.info("TON FlashBet (с TMA и реферальной системой) запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
