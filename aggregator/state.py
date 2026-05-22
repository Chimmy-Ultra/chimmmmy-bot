"""訂閱者與經濟數據 last-seen 狀態的 JSON 持久化。"""
import json
import os
import threading

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBSCRIBERS_FILE = os.path.join(_DIR, "subscribers.json")
STATE_FILE = os.path.join(_DIR, "aggregator_state.json")

_lock = threading.Lock()


def load_subscribers() -> set[int]:
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_subscribers(subs: set[int]) -> None:
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(subs), f)


def add_subscriber(chat_id: int) -> bool:
    with _lock:
        subs = load_subscribers()
        if chat_id in subs:
            return False
        subs.add(chat_id)
        _save_subscribers(subs)
        return True


def remove_subscriber(chat_id: int) -> bool:
    with _lock:
        subs = load_subscribers()
        if chat_id not in subs:
            return False
        subs.discard(chat_id)
        _save_subscribers(subs)
        return True


def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_last_seen(series_id: str) -> str | None:
    return _load_state().get("last_seen", {}).get(series_id)


def set_last_seen(series_id: str, date_str: str) -> None:
    with _lock:
        state = _load_state()
        state.setdefault("last_seen", {})[series_id] = date_str
        _save_state(state)
