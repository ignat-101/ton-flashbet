import os
import json
import time
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
TON_API = os.getenv('TON_API_ENDPOINT', 'https://toncenter.com/api/v2/jsonRPC')
BOT_WALLET = os.getenv('BOT_WALLET_ADDRESS')

# Простая "база данных"
try:
    with open('storage.json', 'r') as f:
        db = json.load(f)
except:
    db = {"bets": {}, "users": {}, "disputes": {}}

def save_db():
    with open('storage.json', 'w') as f:
        json.dump(db, f, indent=2)

# --- Утилиты для TON ---
def check_ton_transaction(tx_hash: str, expected_amount: float, expected_sender: str = None):
    try:
        payload = {"jsonrpc": "2.0", "method": "getTransaction", "params": {"hash": tx_hash}, "id": 1}
        r = requests.post(TON_API, json=payload, timeout=10)
        if r.status_code == 200:
            result = r.json().get('result')
            if result:
                amount = float(result.get('value', 0))
                sender = result.get('from')
                # Проверяем сумму и (опционально) отправителя
                if amount >= expected_amount:
                    if expected_sender and sender != expected_sender:
                        return False
                    return True
    except Exception as e:
        print(f"TON check error: {e}")
    return False

def get_price(asset: str):
    # Бесплатный API для проверки цен (CoinGecko)
    try:
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={asset}&vs_currencies=usd", timeout=5)
        if r.status_code == 200:
            return r.json().get(asset, {}).get('usd')
    except:
        pass
    return None

# --- Хендлеры команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎲 Добро пожаловать в TON FlashBet!\n"
        "Ставки на ВСЁ. Моментально, честно, через TON.\n\n"
        "Команды:\n"
        "/newbet @user 1.0 'BTC > 100k' — создать спор\n"
        "/openbet 5.0 'Снег в Москве' — открытая ставка\n"
        "/mybets — мои активные ставки"
    )

async def new_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Пример: /newbet @friend 1.0 'BTC > 100k'")
        return
    
    try:
        amount = float(args[1])
        condition = ' '.join(args[2:])
        opponent_tag = args[0].replace('@', '')
        
        bet_id = f"bet_{int(time.time())}"
        
        # Сохраняем ставку
        db['bets'][bet_id] = {
            'id': bet_id,
            'initiator': update.effective_user.id,
            'opponent_tag': opponent_tag,
            'amount': amount,
            'condition': condition,
            'status': 'pending',  # Ждем оплаты
            'votes': {'initiator': 0, 'opponent': 0},
            'voters': []
        }
        save_db()
        
        # Генерируем сообщение для оппонента
        keyboard = [[
            InlineKeyboardButton("✅ Принять ставку", callback_data=f"accept_{bet_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{bet_id}")
        ]]
        
        msg = (
            f"🔥 Новая ставка!\n"
            f"📋 Условие: {condition}\n"
            f"💰 Сумма: {amount} TON\n"
            f"👤 От: @{update.effective_user.username}\n\n"
            f"Чтобы принять, отправь {amount} TON на кошелек бота с комментарием: `{bet_id}`"
        )
        
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def accept_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bet_id = query.data.split('_')[1]
    
    if bet_id not in db['bets']:
        await query.edit_message_text("❌ Ставка не найдена.")
        return
    
    bet = db['bets'][bet_id]
    bet['status'] = 'awaiting_payment'
    bet['opponent'] = query.from_user.id
    save_db()
    
    await query.edit_message_text(
        f"✅ Ставка принята!\n"
        f"💳 Отправьте {bet['amount']} TON на адрес:\n`{BOT_WALLET}`\n"
        f"💡 В комментарии укажите: `{bet_id}`\n\n"
        f"После оплаты отправьте хеш транзакции командой:\n`/pay {bet_id} <hash>`"
    )

async def pay_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Пример: /pay bet_12345 <hash_транзакции>")
        return
    
    bet_id = args[0]
    tx_hash = args[1]
    
    if bet_id not in db['bets']:
        await update.message.reply_text("Ставка не найдена.")
        return
    
    bet = db['bets'][bet_id]
    
    # Проверяем транзакцию через TON API
    if check_ton_transaction(tx_hash, bet['amount']):
        # Определяем, кто платит (инициатор или оппонент)
        user_id = update.effective_user.id
        if user_id == bet['initiator']:
            bet['initiator_paid'] = True
        elif user_id == bet.get('opponent'):
            bet['opponent_paid'] = True
        
        # Если оба заплатили — активируем ставку
        if bet.get('initiator_paid') and bet.get('opponent_paid'):
            bet['status'] = 'active'
            await update.message.reply_text(
                f"🎲 Ставка активирована!\n"
                f"Условие: {bet['condition']}\n"
                f"Ждем результата..."
            )
        else:
            await update.message.reply_text("✅ Оплата получена. Ждем оплаты второго участника.")
        
        save_db()
    else:
        await update.message.reply_text("❌ Транзакция не найдена или сумма неверна.")

async def claim_win(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Пример: /won bet_12345")
        return
    
    bet_id = args[0]
    if bet_id not in db['bets']:
        await update.message.reply_text("Ставка не найдена.")
        return
    
    bet = db['bets'][bet_id]
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь участником
    if user_id not in [bet['initiator'], bet.get('opponent')]:
        await update.message.reply_text("❌ Вы не участник этой ставки.")
        return
    
    # Определяем победителя (для MVP — просто заявление)
    # В реальности тут должна быть проверка условия
    bet['status'] = 'claim_pending'
    bet['claimed_winner'] = user_id
    save_db()
    
    # Уведомляем оппонента
    opponent_id = bet['opponent'] if user_id == bet['initiator'] else bet['initiator']
    keyboard = [[
        InlineKeyboardButton("✅ Согласен", callback_data=f"confirm_{bet_id}"),
        InlineKeyboardButton("⚠️ Спор!", callback_data=f"dispute_{bet_id}")
    ]]
    
    # Тут должна быть отправка сообщения оппоненту (упрощенно — просто отвечаем)
    await update.message.reply_text(
        f"🏆 Вы заявляете победу в ставке {bet_id}.\n"
        f"Оппонент уведомлен. Если он не оспорит в течение 1 часа — победа засчитывается.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def vote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith('vote_'):
        _, bet_id, choice = data.split('_')
        user_id = query.from_user.id
        
        bet = db['bets'].get(bet_id)
        if not bet:
            return
        
        # Простейшая защита: нельзя голосовать участникам
        if user_id in [bet['initiator'], bet.get('opponent')]:
            await query.answer("Вы участник ставки!")
            return
        
        # Проверяем, не голосовал ли уже
        if user_id in bet['voters']:
            await query.answer("Вы уже голосовали!")
            return
        
        # Записываем голос
        bet['voters'].append(user_id)
        if choice == 'initiator':
            bet['votes']['initiator'] += 1
        else:
            bet['votes']['opponent'] += 1
        
        save_db()
        await query.edit_message_text(f"✅ Ваш голос учтен! Текущий счет: {bet['votes']}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newbet", new_bet))
    app.add_handler(CommandHandler("pay", pay_bet))
    app.add_handler(CommandHandler("won", claim_win))
    app.add_handler(CallbackQueryHandler(accept_bet, pattern="^accept_"))
    app.add_handler(CallbackQueryHandler(vote_handler, pattern="^vote_"))
    
    print("TON FlashBet Bot started...")
    app.run_polling()

if __name__ == '__main__':
    main()
