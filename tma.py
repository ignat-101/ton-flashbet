from flask import Flask, render_template, request, jsonify, session, redirect, url_for, abort
import os
import json
import time
import sys
import random
import hashlib
import hmac
import logging
from urllib.parse import unquote, parse_qsl
from threading import Lock

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Добавляем путь к shared модулям
sys.path.insert(0, os.path.dirname(__file__))

from shared.db import (
    load_db, save_db, get_user, update_user, get_bet, save_bet, 
    get_treasury, update_treasury, add_treasury_transaction,
    get_referral_info, save_referral_info, validate_user_id, validate_amount
)
from shared.ton import get_crypto_price, get_5min_price_change, get_ton_balance, verify_ton_transaction

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', os.urandom(24).hex())

# Блокировка для concurrent доступа к БД
db_lock = Lock()

def verify_telegram_init_data(init_data: str) -> dict:
    """
    Проверка подписи Telegram WebApp initData.
    Возвращает данные пользователя если подпись верна, иначе None.
    """
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("BOT_TOKEN not set")
        return None
    
    if not init_data:
        return None
    
    try:
        # Парсим данные
        data_dict = dict(parse_qsl(init_data, keep_blank_values=True))
        
        # Извлекаем hash
        received_hash = data_dict.pop('hash', None)
        if not received_hash:
            logger.warning("No hash in initData")
            return None
        
        # Сортируем ключи и создаем data_check_string
        data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(data_dict.items()))
        
        # Создаем секретный ключ из токена бота
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        
        # Вычисляем ожидаемый hash
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        # Сравниваем (используем hmac.compare_digest для защиты от timing attack)
        if not hmac.compare_digest(received_hash, expected_hash):
            logger.warning("Invalid initData signature")
            return None
        
        # Проверяем срок действия (auth_date не старше 1 часа)
        auth_date = int(data_dict.get('auth_date', 0))
        if time.time() - auth_date > 3600:
            logger.warning("initData is too old")
            return None
        
        # Извлекаем данные пользователя
        user_data = {}
        if 'user' in data_dict:
            try:
                user_data = json.loads(data_dict['user'])
            except json.JSONDecodeError:
                logger.error("Failed to parse user data")
                return None
        
        return user_data if user_data else None
        
    except Exception as e:
        logger.error(f"Error verifying initData: {e}")
        return None

def escape_html(text: str) -> str:
    """Escape HTML special characters to prevent XSS."""
    if not text:
        return ""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#x27;'))

def require_auth(f):
    """Decorator to require Telegram WebApp authentication for API routes."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Проверяем initData из заголовков или query params
        init_data = request.headers.get('X-Telegram-Init-Data') or request.args.get('tgWebAppData')
        
        if not init_data:
            return jsonify({'error': 'Authentication required'}), 401
        
        user_data = verify_telegram_init_data(init_data)
        if not user_data:
            return jsonify({'error': 'Invalid authentication data'}), 401
        
        # Добавляем данные пользователя в request context
        request.telegram_user = user_data
        return f(*args, **kwargs)
    
    return decorated_function

@app.route('/')
def index():
    """Главная страница TMA (без проверки Telegram для тестирования)"""
    # УБИРАЕМ ОГРАНИЧЕНИЕ TELEGRAM
    # Тестовый режим - всегда разрешаем доступ
    logger.info("TMA accessed without Telegram check")
    return render_template('tma.html', user_id=12345, username="test_user")

@app.route('/api/prices')
@require_auth
def get_prices():
    """API для получения 5-минутных изменений цен (оракул)"""
    symbols = ['bitcoin', 'ethereum', 'solana', 'ton']
    prices = {}
    
    for symbol in symbols:
        data = get_5min_price_change(symbol)
        if data:
            prices[symbol] = {
                'price': round(data['price'], 2),
                'change': round(data['change_5min'], 4),
                'change_percent': round(data.get('change_5min_percent', 0), 2),
                'direction': data['direction'],
                'emoji': '🔥' if abs(data['change_5min']) > 0.001 else ''
            }
    
    return jsonify(prices)

@app.route('/api/bets')
@require_auth
def get_bets():
    """API для получения списка активных ставок"""
    db = load_db()
    bets = []
    
    for bet_id, bet in db['bets'].items():
        if bet['status'] in ['active', 'pending', 'awaiting_payment', 'claim_pending', 'disputed']:
            # Calculate market probability based on bets
            total_yes = bet.get('total_yes_amount', 0)
            total_no = bet.get('total_no_amount', 0)
            total = total_yes + total_no
            market_probability = (total_yes / total * 100) if total > 0 else 50.0
            
            bets.append({
                'id': bet_id,
                'condition': escape_html(bet['condition']),
                'amount': float(bet['amount']),
                'status': escape_html(bet['status']),
                'created_at': bet['created_at'],
                'initiator': bet['initiator'],
                'opponent': bet.get('opponent'),
                'probability': float(bet.get('probability', 50)),
                'market_probability': round(market_probability, 1),
                'oracle_status': bet.get('oracle_status', 'pending'),
                'total_yes_amount': total_yes,
                'total_no_amount': total_no
            })
    
    return jsonify(bets)

@app.route('/api/bets/create', methods=['POST'])
@require_auth
def create_bet():
    """Создание новой ставки через TMA с валидацией"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data'}), 400
        
        user_id = data.get('user_id')
        opponent_tag = data.get('opponent_tag', '')
        amount = data.get('amount')
        condition = data.get('condition', '')
        
        # Валидация
        if not validate_user_id(user_id):
            return jsonify({'error': 'Invalid user_id'}), 400
        
        if not validate_amount(amount, min_amount=0.1, max_amount=1000):
            return jsonify({'error': 'Invalid amount (must be 0.1-1000 TON)'}), 400
        
        if not condition or len(condition) > 500:
            return jsonify({'error': 'Invalid condition (1-500 chars)'}), 400
        
        if opponent_tag and len(opponent_tag) > 50:
            return jsonify({'error': 'Invalid opponent tag'}), 400
        
        amount_float = float(amount)
        bet_id = f"bet_{int(time.time())}"
        
        new_bet = {
            'id': bet_id,
            'initiator': int(user_id),
            'opponent_tag': escape_html(str(opponent_tag)),
            'amount': amount_float,
            'condition': escape_html(str(condition)),
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
            'suspect_voters': [],
            # Новые поля для торговли вероятностями
            'probability': 50.0,  # Начальная вероятность
            'market_probability': 50.0,
            'total_yes_amount': 0.0,
            'total_no_amount': 0.0,
            'trades': [],  # История торгов
            'oracle_status': 'pending',  # pending, checking, success, failed
            'oracle_condition': None  # Условие для проверки оракулом
        }
        
        # Если ставка на цену криптовалюты, добавляем oracle_condition
        import re
        price_pattern = r'(btc|bitcoin|eth|ethereum|sol|solana|ton|toncoin).*?(\d+[kmb]?|\d+\.?\d*)'  
        match = re.search(price_pattern, condition.lower())
        if match:
            crypto = match.group(1)
            price_target = match.group(2)
            new_bet['oracle_condition'] = f"{crypto.upper()} > {price_target}"
            new_bet['oracle_status'] = 'checking'
        
        if not save_bet(new_bet):
            return jsonify({'error': 'Failed to save bet'}), 500
        
        logger.info(f"Bet created: {bet_id} by user {user_id}")
        return jsonify({'success': True, 'bet_id': bet_id})
        
    except Exception as e:
        logger.error(f"Error creating bet: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/profile')
@require_auth
def get_profile():
    """Получение профиля пользователя"""
    user_id = request.args.get('user_id')
    
    if not validate_user_id(user_id):
        return jsonify({'error': 'Invalid user_id'}), 400
    
    user = get_user(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    referral_info = get_referral_info(user_id)
    treasury = get_treasury()
    
    # Добавляем информацию о кошельке
    wallet_address = user.get('wallet_address', None)
    
    return jsonify({
        'user': user,
        'referral': referral_info,
        'treasury_balance': treasury.get('balance', 0),
        'wallet_address': wallet_address
    })

@app.route('/api/referral/generate')
@require_auth
def generate_referral():
    """Генерация реферальной ссылки"""
    user_id = request.args.get('user_id')
    
    if not validate_user_id(user_id):
        return jsonify({'error': 'Invalid user_id'}), 400
    
    referral_info = get_referral_info(user_id)
    if not referral_info.get('code'):
        code = f"REF{user_id}{random.randint(1000, 9999)}"
        referral_info['code'] = code
        save_referral_info(user_id, referral_info)
    
    bot_username = os.getenv('BOT_USERNAME', 'FlashBetTON_bot')
    referral_link = f"https://t.me/{bot_username}?start={referral_info['code']}"
    
    return jsonify({
        'code': referral_info['code'],
        'link': referral_link
    })

# Новые эндпоинты для торговли и кошелька

@app.route('/api/trade', methods=['POST'])
@require_auth
def trade_bet():
    """Торговля долями ставок (как на Polymarket)"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data'}), 400
        
        bet_id = data.get('bet_id')
        amount = data.get('amount')
        side = data.get('side', 'yes')  # 'yes' or 'no'
        user_id = request.telegram_user.get('id')
        
        if not bet_id or not amount:
            return jsonify({'error': 'Missing bet_id or amount'}), 400
        
        amount_float = float(amount)
        if amount_float < 0.1:
            return jsonify({'error': 'Minimum trade amount is 0.1 TON'}), 400
        
        db = load_db()
        bet = db['bets'].get(bet_id)
        if not bet:
            return jsonify({'error': 'Bet not found'}), 404
        
        if bet['status'] not in ['active', 'pending']:
            return jsonify({'error': 'Bet is not active for trading'}), 400
        
        # Update bet totals based on trade side
        if side == 'yes':
            bet['total_yes_amount'] = bet.get('total_yes_amount', 0) + amount_float
        else:
            bet['total_no_amount'] = bet.get('total_no_amount', 0) + amount_float
        
        # Recalculate market probability
        total_yes = bet.get('total_yes_amount', 0)
        total_no = bet.get('total_no_amount', 0)
        total = total_yes + total_no
        if total > 0:
            bet['market_probability'] = (total_yes / total) * 100
        
        # Add trade to history
        trade_record = {
            'user_id': user_id,
            'amount': amount_float,
            'side': side,
            'timestamp': time.time(),
            'probability_at_time': bet.get('market_probability', 50)
        }
        if 'trades' not in bet:
            bet['trades'] = []
        bet['trades'].append(trade_record)
        
        save_db(db)
        
        logger.info(f"Trade placed: {bet_id} by user {user_id}: {side} {amount_float} TON")
        return jsonify({
            'success': True,
            'market_probability': round(bet['market_probability'], 1),
            'total_yes_amount': bet['total_yes_amount'],
            'total_no_amount': bet['total_no_amount']
        })
        
    except Exception as e:
        logger.error(f"Error trading: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/wallet/connect', methods=['POST'])
@require_auth
def connect_wallet():
    """Подключение TON кошелька к профилю"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data'}), 400
        
        wallet_address = data.get('wallet_address')
        user_id = request.telegram_user.get('id')
        
        if not wallet_address or not isinstance(wallet_address, str):
            return jsonify({'error': 'Invalid wallet address'}), 400
        
        # Validate TON address format (simplified)
        if not wallet_address.startswith('EQ') and not wallet_address.startswith('UQ'):
            return jsonify({'error': 'Invalid TON address format'}), 400
        
        # Update user's wallet address
        db = load_db()
        uid = str(user_id)
        
        if uid not in db['users']:
            return jsonify({'error': 'User not found'}), 404
        
        db['users'][uid]['wallet_address'] = wallet_address
        save_db(db)
        
        logger.info(f"Wallet connected: {wallet_address} to user {user_id}")
        return jsonify({'success': True, 'wallet_address': wallet_address})
        
    except Exception as e:
        logger.error(f"Error connecting wallet: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/wallet/balance')
@require_auth
def get_wallet_balance():
    """Получение баланса кошелька"""
    try:
        address = request.args.get('address')
        
        if not address:
            # Try to get from user profile
            user_id = request.telegram_user.get('id')
            db = load_db()
            user = db['users'].get(str(user_id))
            if user:
                address = user.get('wallet_address')
        
        if not address:
            return jsonify({'error': 'Wallet address not found'}), 400
        
        balance = get_ton_balance(address)
        
        return jsonify({
            'address': address,
            'balance': round(balance, 4)
        })
        
    except Exception as e:
        logger.error(f"Error getting wallet balance: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/wallet/disconnect', methods=['POST'])
@require_auth
def disconnect_wallet():
    """Отключение кошелька"""
    try:
        user_id = request.telegram_user.get('id')
        
        db = load_db()
        uid = str(user_id)
        
        if uid in db['users']:
            db['users'][uid]['wallet_address'] = None
            save_db(db)
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error disconnecting wallet: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/oracle/check', methods=['POST'])
@require_auth
def oracle_check():
    """Проверка условия ставки через оракул (CoinGecko)"""
    try:
        data = request.json
        bet_id = data.get('bet_id')
        
        if not bet_id:
            return jsonify({'error': 'Missing bet_id'}), 400
        
        db = load_db()
        bet = db['bets'].get(bet_id)
        if not bet:
            return jsonify({'error': 'Bet not found'}), 404
        
        if not bet.get('oracle_condition'):
            return jsonify({'error': 'No oracle condition set'}), 400
        
        # Parse oracle condition
        condition = bet['oracle_condition']  # e.g., "BTC > 100000"
        import re
        match = re.match(r'(\w+)\s*([><]=?)\s*([\d.]+)', condition)
        
        if not match:
            return jsonify({'error': 'Invalid oracle condition format'}), 400
        
        crypto = match.group(1).lower()
        operator = match.group(2)
        target_price = float(match.group(3))
        
        # Get current price
        price_data = get_crypto_price(crypto)
        if not price_data:
            return jsonify({'error': 'Failed to get price data'}), 500
        
        current_price = price_data['price']
        
        # Check condition
        condition_met = False
        if operator == '>':
            condition_met = current_price > target_price
        elif operator == '>=':
            condition_met = current_price >= target_price
        elif operator == '<':
            condition_met = current_price < target_price
        elif operator == '<=':
            condition_met = current_price <= target_price
        
        # Update bet status
        bet['oracle_status'] = 'success' if condition_met else 'failed'
        bet['oracle_last_check'] = time.time()
        bet['oracle_current_price'] = current_price
        
        if condition_met:
            bet['status'] = 'completed'
            bet['winner'] = bet['initiator']  # Simplified - should determine actual winner
        
        save_db(db)
        
        return jsonify({
            'success': True,
            'condition_met': condition_met,
            'current_price': current_price,
            'oracle_status': bet['oracle_status']
        })
        
    except Exception as e:
        logger.error(f"Oracle check error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/treasury')
@require_auth
def get_treasury_info():
    """Публичная информация о казне"""
    treasury = get_treasury()
    recent_tx = treasury.get('transactions', [])[-10:]
    
    wallet_address = os.getenv('BOT_WALLET_ADDRESS')
    real_balance = get_ton_balance(wallet_address) if wallet_address else 0
    
    return jsonify({
        'balance': treasury.get('balance', 0),
        'real_balance': real_balance,
        'wallet_address': wallet_address,
        'recent_transactions': recent_tx
    })

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden', 'message': str(e.description)}), 403

@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad Request', 'message': str(e.description)}), 400

# Serve TON Connect manifest
@app.route('/tonconnect-manifest.json')
def tonconnect_manifest():
    """Manifest for TON Connect"""
    return jsonify({
        "url": request.host_url.rstrip('/'),
        "name": "TON FlashBet",
        "iconUrl": f"{request.host_url}static/icon.png",
        "termsOfUseUrl": f"{request.host_url}terms",
        "privacyPolicyUrl": f"{request.host_url}privacy"
    })


if __name__ == '__main__':
    # Создаем директорию templates если её нет
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    # Render требует порт из переменной PORT
    port = int(os.getenv('PORT', 5000))
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
