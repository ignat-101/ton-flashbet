import requests
import time
import os
import hashlib
import hmac
import logging
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TON_API_ENDPOINT = os.getenv('TON_API_ENDPOINT', 'https://toncenter.com/api/v2/jsonRPC')
TON_API_KEY = os.getenv('TON_API_KEY', '')

# Rate limiting
class RateLimiter:
    def __init__(self, calls_per_minute=30):
        self.calls_per_minute = calls_per_minute
        self.calls = []
    
    def can_call(self):
        now = time.time()
        # Remove calls older than 1 minute
        self.calls = [t for t in self.calls if now - t < 60]
        return len(self.calls) < self.calls_per_minute
    
    def record_call(self):
        self.calls.append(time.time())

ton_rate_limiter = RateLimiter(calls_per_minute=30)
coingecko_rate_limiter = RateLimiter(calls_per_minute=50)

# Кэш для цен криптовалют
price_cache = {}
price_cache_time = {}
CACHE_TTL = 60  # 1 minute

def verify_ton_transaction(tx_hash: str, expected_amount: float, expected_recipient: str = None) -> Dict[str, Any]:
    """
    Проверка транзакции в сети TON с валидацией.
    Возвращает dict с результатом проверки.
    """
    result = {
        'valid': False,
        'amount': 0,
        'from_address': None,
        'to_address': None,
        'error': None
    }
    
    if not tx_hash or not isinstance(tx_hash, str):
        result['error'] = 'Invalid transaction hash'
        return result
    
    if expected_amount <= 0:
        result['error'] = 'Invalid expected amount'
        return result
    
    # Rate limiting
    if not ton_rate_limiter.can_call():
        result['error'] = 'Rate limit exceeded, try again later'
        return result
    
    try:
        ton_rate_limiter.record_call()
        
        headers = {}
        if TON_API_KEY:
            headers['X-API-Key'] = TON_API_KEY
        
        payload = {
            "jsonrpc": "2.0", 
            "method": "getTransaction", 
            "params": {"hash": tx_hash}, 
            "id": 1
        }
        
        r = requests.post(TON_API_ENDPOINT, json=payload, headers=headers, timeout=10)
        
        if r.status_code != 200:
            result['error'] = f'API returned status {r.status_code}'
            logger.warning(f"TON API error: {r.status_code} - {r.text[:200]}")
            return result
        
        data = r.json()
        
        if 'error' in data:
            result['error'] = f"TON API error: {data['error']}"
            logger.error(f"TON API error: {data['error']}")
            return result
        
        result_data = data.get('result')
        if not result_data:
            result['error'] = 'Transaction not found'
            return result
        
        # Проверяем сумму (конвертируем из наноTON)
        amount_nano = float(result_data.get('value', 0))
        amount_ton = amount_nano / 1e9
        
        result['amount'] = amount_ton
        result['from_address'] = result_data.get('from')
        result['to_address'] = result_data.get('to')
        
        # Проверяем сумму
        if amount_ton < expected_amount:
            result['error'] = f'Amount mismatch: expected {expected_amount}, got {amount_ton}'
            return result
        
        # Проверяем получателя, если указан
        if expected_recipient and result_data.get('to') != expected_recipient:
            result['error'] = f'Recipient mismatch: expected {expected_recipient}, got {result_data.get("to")}'
            return result
        
        result['valid'] = True
        logger.info(f"Transaction {tx_hash} verified: {amount_ton} TON")
        
    except requests.Timeout:
        result['error'] = 'Request timeout'
        logger.error(f"Timeout checking transaction {tx_hash}")
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"TON transaction check error: {e}")
    
    return result

def get_ton_balance(wallet_address: str) -> float:
    """Получение баланса кошелька TON с кэшированием."""
    if not wallet_address or not isinstance(wallet_address, str):
        return 0.0
    
    # Простой кэш на 30 секунд
    cache_key = f"balance_{wallet_address}"
    current_time = time.time()
    
    if cache_key in price_cache and (current_time - price_cache_time.get(cache_key, 0)) < 30:
        return price_cache[cache_key]
    
    if not ton_rate_limiter.can_call():
        return price_cache.get(cache_key, 0.0)
    
    try:
        ton_rate_limiter.record_call()
        
        headers = {}
        if TON_API_KEY:
            headers['X-API-Key'] = TON_API_KEY
        
        payload = {
            "jsonrpc": "2.0",
            "method": "getAddressBalance",
            "params": {"address": wallet_address},
            "id": 1
        }
        
        r = requests.post(TON_API_ENDPOINT, json=payload, headers=headers, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            if 'result' in data and data['result']:
                balance = float(data['result']) / 1e9
                price_cache[cache_key] = balance
                price_cache_time[cache_key] = current_time
                return balance
                
    except Exception as e:
        logger.error(f"TON balance check error for {wallet_address}: {e}")
    
    return price_cache.get(cache_key, 0.0)

# Кэш для цен криптовалют
price_cache = {}
price_cache_time = {}
CACHE_TTL = 60  # 1 minute

def get_crypto_price(symbol: str, currency: str = 'usd') -> Optional[Dict]:
    """Получение цены криптовалюты через CoinGecko API с кэшированием."""
    if not symbol:
        return None
    
    current_time = time.time()
    cache_key = f"{symbol}_{currency}"
    
    # Используем кэш
    if cache_key in price_cache and (current_time - price_cache_time.get(cache_key, 0)) < CACHE_TTL:
        return price_cache[cache_key]
    
    # Rate limiting
    if not coingecko_rate_limiter.can_call():
        logger.warning("CoinGecko rate limit reached")
        return price_cache.get(cache_key)
    
    try:
        coingecko_rate_limiter.record_call()
        
        # Маппинг символов на ID CoinGecko
        symbol_map = {
            'bitcoin': 'bitcoin',
            'ethereum': 'ethereum',
            'solana': 'solana',
            'ton': 'the-open-network',
            'toncoin': 'the-open-network',
            'btc': 'bitcoin',
            'eth': 'ethereum',
            'sol': 'solana'
        }
        
        coin_id = symbol_map.get(symbol.lower())
        if not coin_id:
            logger.warning(f"Unknown symbol: {symbol}")
            return None
        
        url = f"https://api.coingecko.com/api/v3/simple/price"
        params = {
            'ids': coin_id,
            'vs_currencies': currency,
            'include_24hr_change': 'true',
            'include_last_updated_at': 'true'
        }
        
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            if coin_id in data:
                price_data = {
                    'symbol': symbol,
                    'price': float(data[coin_id].get(currency, 0)),
                    'change_24h': float(data[coin_id].get(f'{currency}_24h_change', 0)),
                    'last_updated': data[coin_id].get('last_updated_at', current_time)
                }
                price_cache[cache_key] = price_data
                price_cache_time[cache_key] = current_time
                return price_data
        elif r.status_code == 429:
            logger.warning("CoinGecko rate limit exceeded")
        else:
            logger.error(f"CoinGecko API error: {r.status_code}")
            
    except requests.Timeout:
        logger.error(f"Timeout fetching price for {symbol}")
    except Exception as e:
        logger.error(f"Price fetch error for {symbol}: {e}")
    
    # Возвращаем кэшированные данные, если есть
    return price_cache.get(cache_key)

def get_5min_price_change(symbol: str) -> Optional[Dict]:
    """
    Получение изменения цены за 5 минут.
    ВНИМАНИЕ: Требует исторического API, в MVP используем эвристику на основе 24ч изменения.
    Для продакшена нужно использовать CoinGecko Pro API или другой источник исторических данных.
    """
    current_data = get_crypto_price(symbol)
    if not current_data:
        return None
    
    # Для реального 5-минутного изменения нужен доступ к историческим данным
    # Пока используем эвристику: берем от 24ч изменения
    change_24h = current_data.get('change_24h', 0)
    
    # Эвристика: 5min change ~ 1/10 от 24h change с добавлением случайного шума
    # В реальности здесь должен быть запрос к API исторических данных
    import random
    noise = random.uniform(-0.1, 0.1)
    change_5min = (change_24h / 10) + noise if change_24h else noise * 0.01
    
    return {
        'symbol': symbol,
        'price': current_data['price'],
        'change_5min': change_5min,
        'change_5min_percent': (change_5min / current_data['price']) * 100 if current_data['price'] > 0 else 0,
        'direction': 'up' if change_5min >= 0 else 'down',
        'timestamp': time.time(),
        'note': 'MVP: 5min change is estimated, not real historical data'
    }
