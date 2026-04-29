"""
SQLite database module for TON FlashBet.
More robust than JSON for production use.
"""

import sqlite3
import json
import os
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DB_PATH', 'flashbet.db')
BACKUP_PATH = os.getenv('DB_BACKUP_PATH', 'backups')

def init_db():
    """Initialize SQLite database with all required tables."""
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else '.', exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        reputation INTEGER DEFAULT 100,
        account_age_days INTEGER DEFAULT 365,
        mutual_groups INTEGER DEFAULT 5,
        successful_votes INTEGER DEFAULT 0,
        failed_votes INTEGER DEFAULT 0,
        staked_ton REAL DEFAULT 0.0,
        total_earned REAL DEFAULT 0.0,
        total_lost REAL DEFAULT 0.0,
        referral_code TEXT,
        referred_by INTEGER,
        referrals_count INTEGER DEFAULT 0,
        referral_earnings REAL DEFAULT 0.0,
        created_at REAL,
        updated_at REAL
    )''')
    
    # Bets table
    c.execute('''CREATE TABLE IF NOT EXISTS bets (
        id TEXT PRIMARY KEY,
        initiator INTEGER,
        opponent_tag TEXT,
        opponent INTEGER,
        amount REAL,
        condition TEXT,
        status TEXT,
        winner INTEGER,
        created_at REAL,
        updated_at REAL,
        data_json TEXT
    )''')
    
    # Treasury table
    c.execute('''CREATE TABLE IF NOT EXISTS treasury (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        balance REAL DEFAULT 0.0,
        updated_at REAL
    )''')
    
    # Transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        amount REAL,
        description TEXT,
        user_id INTEGER,
        timestamp REAL,
        bet_id TEXT
    )''')
    
    # Referrals table
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        user_id INTEGER PRIMARY KEY,
        code TEXT,
        referred_by INTEGER,
        referrals TEXT,  -- JSON array
        earnings REAL DEFAULT 0.0
    )''')
    
    # Votes table
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bet_id TEXT,
        user_id INTEGER,
        choice TEXT,
        weight REAL,
        stake REAL,
        timestamp REAL
    )''')
    
    # Initialize treasury if not exists
    c.execute("SELECT COUNT(*) FROM treasury")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO treasury (balance, updated_at) VALUES (0.0, ?)", (time.time(),))
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_from_json(json_path='storage.json'):
    """Migrate data from JSON file to SQLite."""
    if not os.path.exists(json_path):
        logger.warning(f"JSON file {json_path} not found, skipping migration")
        return
    
    logger.info(f"Starting migration from {json_path} to SQLite...")
    
    import shutil
    if os.path.exists(DB_PATH):
        backup_name = f"{DB_PATH}.backup_{int(time.time())}"
        shutil.copy2(DB_PATH, backup_name)
        logger.info(f"Existing DB backed up to {backup_name}")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Migrate users
        for uid, user in data.get('users', {}).items():
            c.execute('''INSERT OR REPLACE INTO users 
                (id, username, reputation, account_age_days, mutual_groups,
                 successful_votes, failed_votes, staked_ton, total_earned,
                 total_lost, referral_code, referred_by, referrals_count,
                 referral_earnings, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    int(uid), user.get('username', ''),
                    user.get('reputation', 100),
                    user.get('account_age_days', 365),
                    user.get('mutual_groups', 5),
                    user.get('successful_votes', 0),
                    user.get('failed_votes', 0),
                    user.get('staked_ton', 0.0),
                    user.get('total_earned', 0.0),
                    user.get('total_lost', 0.0),
                    user.get('referral_code'),
                    user.get('referred_by'),
                    user.get('referrals_count', 0),
                    user.get('referral_earnings', 0.0),
                    user.get('created_at', time.time()),
                    time.time()
                )
            )
        
        # Migrate bets
        for bet_id, bet in data.get('bets', {}).items():
            c.execute('''INSERT OR REPLACE INTO bets
                (id, initiator, opponent_tag, opponent, amount, condition,
                 status, winner, created_at, updated_at, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    bet_id, bet.get('initiator'),
                    bet.get('opponent_tag', ''),
                    bet.get('opponent'),
                    bet.get('amount', 0.0),
                    bet.get('condition', ''),
                    bet.get('status', 'pending'),
                    bet.get('winner'),
                    bet.get('created_at', time.time()),
                    time.time(),
                    json.dumps(bet)
                )
            )
        
        # Migrate treasury
        treasury = data.get('treasury', {})
        c.execute("DELETE FROM treasury")
        c.execute("INSERT INTO treasury (balance, updated_at) VALUES (?, ?)",
                 (treasury.get('balance', 0.0), time.time()))
        
        # Migrate transactions
        for tx in treasury.get('transactions', []):
            c.execute('''INSERT INTO transactions
                (type, amount, description, user_id, timestamp, bet_id)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    tx.get('type', ''),
                    tx.get('amount', 0.0),
                    tx.get('description', ''),
                    tx.get('user_id'),
                    tx.get('timestamp', time.time()),
                    None
                )
            )
        
        conn.commit()
        logger.info("Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        conn.close()

# User operations
def get_user(user_id: int, username: str = "") -> Optional[Dict]:
    """Get or create a user."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    
    if row:
        user = dict(row)
    else:
        # Create new user
        user = {
            'id': user_id,
            'username': username[:50] if username else "",
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
            'created_at': time.time(),
            'updated_at': time.time()
        }
        
        c.execute('''INSERT INTO users 
            (id, username, reputation, account_age_days, mutual_groups,
             successful_votes, failed_votes, staked_ton, total_earned,
             total_lost, referral_code, referred_by, referrals_count,
             referral_earnings, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            tuple(user.values())
        )
        conn.commit()
    
    conn.close()
    return user

# Similar functions for bets, treasury, etc.
# (Implement as needed, following the same pattern)

if __name__ == '__main__':
    init_db()
    print("Database initialized. Run migrate_from_json() to import data.")
