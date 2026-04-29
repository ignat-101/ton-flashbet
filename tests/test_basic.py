"""
Unit tests for TON FlashBet critical functions.
Run with: pytest tests/test_basic.py -v
"""

import sys
import os
import pytest
import json
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db import (
    validate_user_id, validate_amount, 
    load_db, save_db, get_user, update_user,
    get_bet, save_bet, get_treasury, add_treasury_transaction
)
from shared.ton import verify_ton_transaction, get_crypto_price, RateLimiter
from tma import verify_telegram_init_data, escape_html


class TestValidation:
    """Test validation functions"""
    
    def test_validate_user_id_valid(self):
        assert validate_user_id(12345678) == True
        assert validate_user_id("12345678") == True
    
    def test_validate_user_id_invalid(self):
        assert validate_user_id(0) == False
        assert validate_user_id(-1) == False
        assert validate_user_id("invalid") == False
        assert validate_user_id(None) == False
    
    def test_validate_amount_valid(self):
        assert validate_amount(0.1) == True
        assert validate_amount(500) == True
        assert validate_amount(1000) == True
    
    def test_validate_amount_invalid(self):
        assert validate_amount(0.01) == False  # Too small
        assert validate_amount(1001) == False   # Too large
        assert validate_amount(-1) == False
        assert validate_amount("invalid") == False


class TestDatabase:
    """Test database operations"""
    
    def setup_method(self):
        """Clean up before each test"""
        self.test_db = {
            "bets": {},
            "users": {},
            "disputes": {},
            "referrals": {},
            "treasury": {"balance": 0.0, "transactions": []}
        }
    
    def test_get_user_new(self):
        user = get_user(12345, "testuser")
        assert user is not None
        assert user['id'] == 12345
        assert user['username'] == "testuser"
        assert user['reputation'] == 100
    
    def test_get_user_existing(self):
        # Create user first
        get_user(12345, "testuser")
        # Get same user
        user = get_user(12345, "testuser")
        assert user['id'] == 12345
    
    def test_update_user(self):
        get_user(12345, "testuser")
        updated = update_user(12345, {"reputation": 150, "total_earned": 10.5})
        assert updated is not None
        assert updated['reputation'] == 150
        assert updated['total_earned'] == 10.5
    
    def test_save_and_get_bet(self):
        bet_data = {
            'id': 'bet_12345',
            'initiator': 12345,
            'amount': 1.0,
            'condition': 'BTC > 100k',
            'status': 'pending'
        }
        result = save_bet(bet_data)
        assert result == True
        
        retrieved = get_bet('bet_12345')
        assert retrieved is not None
        assert retrieved['id'] == 'bet_12345'
        assert retrieved['amount'] == 1.0
    
    def test_get_bet_invalid(self):
        assert get_bet(None) is None
        assert get_bet("") is None
        assert get_bet(123) is None
    
    def test_treasury_transaction(self):
        tx = add_treasury_transaction('fee', 0.5, 'Test fee')
        assert tx is not None
        assert tx['type'] == 'fee'
        assert tx['amount'] == 0.5
        
        treasury = get_treasury()
        assert treasury['balance'] == 0.5


class TestSecurity:
    """Test security functions"""
    
    def test_escape_html(self):
        assert escape_html('<script>alert("XSS")</script>') == '&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;'
        assert escape_html('Hello & "World"') == 'Hello &amp; &quot;World&quot;'
        assert escape_html(None) == ""
        assert escape_html("") == ""
    
    def test_verify_init_data_invalid(self):
        # Test with invalid data
        result = verify_telegram_init_data("")
        assert result is None
        
        result = verify_telegram_init_data("invalid_data")
        assert result is None


class TestTON:
    """Test TON-related functions"""
    
    def test_rate_limiter(self):
        limiter = RateLimiter(calls_per_minute=5)
        # Should allow 5 calls
        for i in range(5):
            assert limiter.can_call() == True
            limiter.record_call()
        
        # 6th call should be blocked
        assert limiter.can_call() == False
    
    def test_verify_transaction_invalid_hash(self):
        result = verify_ton_transaction("", 1.0)
        assert result['valid'] == False
        assert result['error'] is not None
        
        result = verify_ton_transaction(None, 1.0)
        assert result['valid'] == False
    
    def test_get_crypto_price_cache(self):
        # First call
        price1 = get_crypto_price('bitcoin')
        # Second call should use cache (if within TTL)
        price2 = get_crypto_price('bitcoin')
        
        if price1 and price2:
            assert price1['symbol'] == price2['symbol']
            assert price1['price'] == price2['price']


class TestIntegration:
    """Integration tests"""
    
    def test_full_bet_flow(self):
        """Test creating and retrieving a bet"""
        # Create user
        user = get_user(99999, "bet_creator")
        assert user is not None
        
        # Create bet
        bet = {
            'id': 'integration_test_bet',
            'initiator': 99999,
            'opponent_tag': '@opponent',
            'amount': 2.5,
            'condition': 'ETH > 3000',
            'status': 'pending',
            'created_at': time.time()
        }
        
        assert save_bet(bet) == True
        
        # Retrieve bet
        retrieved = get_bet('integration_test_bet')
        assert retrieved['amount'] == 2.5
        assert retrieved['condition'] == 'ETH > 3000'
        
        # Cleanup
        db = load_db()
        if 'integration_test_bet' in db['bets']:
            del db['bets']['integration_test_bet']
            save_db(db)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
