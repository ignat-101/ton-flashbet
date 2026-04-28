import json
import time
from typing import Dict, Optional, List

# Простое хранилище в JSON (для MVP)
DATA_FILE = "storage.json"

def load_data() -> Dict:
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"bets": {}, "users": {}, "disputes": {}}

def save_data(data: Dict):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Модели ---

class User:
    def __init__(self, user_id: int, username: str = ""):
        self.id = user_id
        self.username = username
        self.reputation = 0  # Репутация за честные голоса
        self.staked_ton = 0.0 # Сколько TON на счету (для ставок)

class Bet:
    def __init__(self, bet_id: str, initiator_id: int, opponent_id: Optional[int], amount: float, condition: str):
        self.id = bet_id
        self.initiator = initiator_id
        self.opponent = opponent_id  # None для открытых ставок
        self.amount = amount
        self.condition = condition
        self.status = "pending"  # pending, active, claim_pending, disputed, finished
        self.winner = None
        self.created_at = time.time()
        self.deadline = None  # Срок исполнения условия
        self.votes = {"for_initiator": 0, "for_opponent": 0}
        self.voters = []  # Список ID тех, кто проголосовал

    def to_dict(self):
        return self.__dict__

class Dispute:
    def __init__(self, bet_id: str, initiator_id: int):
        self.bet_id = bet_id
        self.initiator = initiator_id
        self.created_at = time.time()
        self.status = "open"  # open, closed
        self.votes = {}  # user_id: "initiator" / "opponent"
