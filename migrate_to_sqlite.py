#!/usr/bin/env python3
"""
Migration script: JSON to SQLite for TON FlashBet.
Run this script to migrate your JSON database to SQLite.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db_sqlite import init_db, migrate_from_json

def main():
    print("=" * 60)
    print("TON FlashBet Database Migration Tool")
    print("=" * 60)
    print()
    
    print("[1/3] Initializing SQLite database...")
    init_db()
    print("✓ Database initialized")
    print()
    
    json_path = 'storage.json'
    if not os.path.exists(json_path):
        print(f"⚠ Warning: {json_path} not found!")
        print("Continuing with empty database...")
    else:
        print(f"[2/3] Migrating data from {json_path}...")
        try:
            migrate_from_json(json_path)
            print("✓ Migration completed successfully!")
        except Exception as e:
            print(f"✗ Migration failed: {e}")
            return 1
    
    print()
    print("[3/3] Verifying migration...")
    from shared.db_sqlite import get_db_connection
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    users_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM bets")
    bets_count = c.fetchone()[0]
    
    c.execute("SELECT balance FROM treasury")
    treasury_row = c.fetchone()
    treasury_balance = treasury_row[0] if treasury_row else 0.0
    
    conn.close()
    
    print(f"✓ Users: {users_count}")
    print(f"✓ Bets: {bets_count}")
    print(f"✓ Treasury balance: {treasury_balance}")
    print()
    print("=" * 60)
    print("Migration completed! Next steps:")
    print("=" * 60)
    print()
    print("1. Update your code to use shared.db_sqlite instead of shared.db")
    print("2. Set environment variable: export DB_PATH=flashbet.db")
    print("3. Restart your application")
    print()
    print("To rollback: Replace shared/db_sqlite.py imports with shared/db.py")
    print()
    return 0

if __name__ == '__main__':
    exit(main())
