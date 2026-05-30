"""
Daily LinkedIn send cap tracker.

LinkedIn enforces ~20 connection requests per day.
Talon tracks this in a local JSON file so the automation runner
can stop gracefully before hitting the limit.

The cap resets at midnight UTC each day.
Override via LINKEDIN_DAILY_CAP env var (default: 19 — conservative buffer).
"""
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Any, List

DAILY_CAP = int(os.getenv("LINKEDIN_DAILY_CAP", "19"))
CAP_FILE = Path(__file__).parent.parent / ".send_cap.json"


def _load() -> Dict[str, Any]:
    if CAP_FILE.exists():
        try:
            with open(CAP_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: Dict[str, Any]) -> None:
    with open(CAP_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _today_key() -> str:
    return str(date.today())


def get_today_count() -> int:
    """Return the number of connection requests sent today."""
    return _load().get(_today_key(), 0)


def increment_count(by: int = 1) -> int:
    """Increment today's send count. Returns the new total."""
    data = _load()
    key = _today_key()
    data[key] = data.get(key, 0) + by
    # Prune old keys (keep last 30 days)
    cutoff = str(date.today() - timedelta(days=30))
    data = {k: v for k, v in data.items() if k >= cutoff}
    _save(data)
    return data[key]


def get_remaining() -> int:
    """Return how many sends are left for today."""
    return max(0, DAILY_CAP - get_today_count())


def is_capped() -> bool:
    """Return True if today's limit has been reached."""
    return get_today_count() >= DAILY_CAP


def get_status() -> Dict[str, Any]:
    """Return full status dict for the API."""
    count = get_today_count()
    remaining = max(0, DAILY_CAP - count)
    pct = min(100, round((count / DAILY_CAP) * 100)) if DAILY_CAP > 0 else 0
    return {
        "daily_cap": DAILY_CAP,
        "sent_today": count,
        "remaining_today": remaining,
        "is_capped": count >= DAILY_CAP,
        "pct_used": pct,
        "date": _today_key(),
    }


def get_history(days: int = 14) -> List[Dict[str, Any]]:
    """Return send counts for the last N days."""
    data = _load()
    result = []
    for i in range(days - 1, -1, -1):
        d = str(date.today() - timedelta(days=i))
        result.append({"date": d, "count": data.get(d, 0)})
    return result
