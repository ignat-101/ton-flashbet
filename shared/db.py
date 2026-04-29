import json
import os
import time
import shutil
import logging
from threading import Lock
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# File lock to prevent concurrent writes
db_lock = Lock()
DB_FILE = 'storage.json'
BACKUP_DIR = 'backups'

def ensure_backup_dir():
    """Ensure backup directory exists"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

def load_db():
    """Load the database from file with validation."""
    if not os.path.exists(DB_FILE):
        logger.info(f"Database file {DB_FILE} not found, creating new one")
        return {
            "bets": {}, 
            "users": {}, 
            "disputes": {}, 
            "referrals": {}, 
            "treasury": {"balance": 0.0, "transactions": []},
            "schema_version": 1
        }
    
    with db_lock:
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Валидация структуры
                required_keys = ["bets", "users", "disputes", "referrals", "treasury"]
                for key in required_keys:
                    if key not in data:
                        data[key] = {} if key != "treasury" else {"balance": 0.0, "transactions": []}
                
                # Проверка типов
                if not isinstance(data["bets"], dict):
                    data["bets"] = {}
                if not isinstance(data["users"], dict):
                    data["users"] = {}
                    
                return data
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in {DB_FILE}: {e}")
            # Пытаемся восстановить из бэкапа
            return restore_from_backup()
        except Exception as e:
            logger.error(f"Error loading database: {e}")
            return restore_from_backup()

def backup_db():
    """Create a backup of the current database"""
    if not os.path.exists(DB_FILE):
        return
    
    ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"storage_{timestamp}.json")
    
    try:
        shutil.copy2(DB_FILE, backup_file)
        logger.info(f"Database backed up to {backup_file}")
        
        # Оставляем только последние 10 бэкапов
        cleanup_old_backups()
    except Exception as e:
        logger.error(f"Backup failed: {e}")

def cleanup_old_backups(keep=10):
    """Remove old backups, keeping only the most recent ones"""
    if not os.path.exists(BACKUP_DIR):
        return
    
    backups = sorted([
        os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) 
        if f.startswith("storage_") and f.endswith(".json")
    ], key=os.path.getmtime)
    
    while len(backups) > keep:
        old_backup = backups.pop(0)
        try:
            os.remove(old_backup)
            logger.info(f"Removed old backup: {old_backup}")
        except Exception as e:
            logger.error(f"Failed to remove old backup {old_backup}: {e}")

def restore_from_backup():
    """Try to restore database from the most recent backup"""
    if not os.path.exists(BACKUP_DIR):
        logger.warning("No backup directory found, creating empty database")
        return {"bets": {}, "users": {}, "disputes": {}, "referrals": {}, "treasury": {"balance": 0.0, "transactions": []}}
    
    backups = sorted([
        os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) 
        if f.startswith("storage_") and f.endswith(".json")
    ], key=os.path.getmtime, reverse=True)
    
    for backup in backups:
        try:
            with open(backup, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"Restored database from backup: {backup}")
            return data
        except Exception as e:
            logger.error(f"Failed to restore from {backup}: {e}")
    
    logger.error("No valid backup found")
    return {"bets": {}, "users": {}, "disputes": {}, "referrals": {}, "treasury": {"balance": 0.0, "transactions": []}}

def save_db(db):
    """Save the database to file atomically (write to temp, then rename)."""
    with db_lock:
        # Create backup before saving
        if os.path.exists(DB_FILE):
            backup_db()
        
        temp_file = f"{DB_FILE}.tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            
            # Atomic rename (works on Linux/Windows NTFS)
            os.replace(temp_file, DB_FILE)
            logger.debug("Database saved successfully")
        except Exception as e:
            logger.error(f"Failed to save database: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise

def get_user(user_id, username=""):
    """Get or create a user with validation."""
    if not isinstance(user_id, (int, str)):
        logger.error(f"Invalid user_id type: {type(user_id)}")
        return None
    
    db = load_db()
    uid = str(user_id)
    
    if uid not in db['users']:
        logger.info(f"Creating new user: {uid}")
        db['users'][uid] = {
            'id': int(user_id) if isinstance(user_id, str) else user_id,
            'username': str(username)[:50] if username else "",  # Limit username length
            'reputation': 100,
            'account_age_days': 365,
            'mutual_groups': 5,
            'successful_votes': 0,
            'failed_votes': 0,
            'staked_ton': 0.0,
            'total_earned': 0.0,
            'total_lost': 0.0,
            'referral_code': None,
            'referred_by': None,
            'referrals_count': 0,
            'referral_earnings': 0.0,
            'created_at': time.time()
        }
        save_db(db)
    
    return db['users'][uid]

def update_user(user_id, updates):
    """Update a user's fields with validation."""
    if not isinstance(updates, dict):
        logger.error("Updates must be a dictionary")
        return None
    
    db = load_db()
    uid = str(user_id)
    
    if uid in db['users']:
        # Validate numeric fields
        numeric_fields = ['reputation', 'account_age_days', 'mutual_groups', 
                         'successful_votes', 'failed_votes', 'staked_ton', 
                         'total_earned', 'total_lost', 'referrals_count', 'referral_earnings']
        
        for key, value in updates.items():
            if key in numeric_fields and not isinstance(value, (int, float)):
                logger.warning(f"Invalid type for {key}: expected number, got {type(value)}")
                updates[key] = float(value) if value else 0.0
        
        db['users'][uid].update(updates)
        save_db(db)
        return db['users'][uid]
    return None

def get_bet(bet_id):
    """Get a bet by ID with validation."""
    if not bet_id or not isinstance(bet_id, str):
        return None
    
    db = load_db()
    bet = db['bets'].get(bet_id)
    
    # Validate bet structure
    if bet and not isinstance(bet, dict):
        logger.error(f"Invalid bet data for {bet_id}")
        return None
    
    return bet

def save_bet(bet):
    """Save or update a bet with validation."""
    if not bet or 'id' not in bet:
        logger.error("Invalid bet data")
        return False
    
    # Validate required fields
    required_fields = ['id', 'initiator', 'amount', 'condition', 'status']
    for field in required_fields:
        if field not in bet:
            logger.error(f"Missing required field {field} in bet")
            return False
    
    # Validate amount
    try:
        amount = float(bet['amount'])
        if amount <= 0 or amount > 1000000:  # Reasonable limits
            logger.warning(f"Suspicious bet amount: {amount}")
    except (ValueError, TypeError):
        logger.error(f"Invalid bet amount: {bet.get('amount')}")
        return False
    
    db = load_db()
    db['bets'][bet['id']] = bet
    save_db(db)
    return True

def get_treasury():
    """Get treasury info."""
    db = load_db()
    if 'treasury' not in db:
        db['treasury'] = {"balance": 0.0, "transactions": []}
        save_db(db)
    return db['treasury']

def update_treasury(updates):
    """Update treasury."""
    db = load_db()
    if 'treasury' not in db:
        db['treasury'] = {"balance": 0.0, "transactions": []}
    db['treasury'].update(updates)
    save_db(db)
    return db['treasury']

def add_treasury_transaction(tx_type, amount, description, user_id=None):
    """Add a transaction to treasury history with validation."""
    # Validate transaction type
    valid_types = ['fee', 'stake_lost', 'stake_returned', 'bonus_paid', 'referral_bonus', 'deposit', 'withdraw']
    if tx_type not in valid_types:
        logger.warning(f"Unknown transaction type: {tx_type}")
    
    # Validate amount
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        logger.error(f"Invalid transaction amount: {amount}")
        return None
    
    db = load_db()
    if 'treasury' not in db:
        db['treasury'] = {"balance": 0.0, "transactions": []}
    
    tx = {
        'type': tx_type,
        'amount': amount,
        'description': str(description)[:200],  # Limit description length
        'user_id': str(user_id) if user_id else None,
        'timestamp': time.time()
    }
    
    db['treasury']['transactions'].append(tx)
    
    # Update balance
    if tx_type in ['fee', 'stake_lost', 'deposit']:
        db['treasury']['balance'] += amount
    elif tx_type in ['stake_returned', 'bonus_paid', 'referral_bonus', 'withdraw']:
        db['treasury']['balance'] -= amount
    
    # Keep only last 1000 transactions
    if len(db['treasury']['transactions']) > 1000:
        db['treasury']['transactions'] = db['treasury']['transactions'][-1000:]
    
    save_db(db)
    return tx

def get_referral_info(user_id):
    """Get referral info for a user."""
    db = load_db()
    uid = str(user_id)
    
    if 'referrals' not in db:
        db['referrals'] = {}
    
    if uid not in db['referrals']:
        db['referrals'][uid] = {
            'code': None,
            'referred_by': None,
            'referrals': [],
            'earnings': 0.0
        }
        save_db(db)
    
    return db['referrals'][uid]

def save_referral_info(user_id, info):
    """Save referral info with validation."""
    if not isinstance(info, dict):
        logger.error("Referral info must be a dictionary")
        return False
    
    db = load_db()
    uid = str(user_id)
    
    if 'referrals' not in db:
        db['referrals'] = {}
    
    db['referrals'][uid] = info
    save_db(db)
    return True

def validate_user_id(user_id):
    """Validate user_id is a valid Telegram user ID"""
    try:
        uid = int(user_id)
        # Telegram user IDs are positive integers, typically > 0
        return uid > 0
    except (ValueError, TypeError):
        return False

def validate_amount(amount_str, min_amount=0.1, max_amount=1000):
    """Validate bet amount"""
    try:
        amount = float(amount_str)
        return min_amount <= amount <= max_amount
    except (ValueError, TypeError):
        return False
