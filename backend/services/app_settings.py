"""Persisted app settings (Instantly campaign ID, etc.)."""
import json
from pathlib import Path
from typing import Any, Dict

SETTINGS_PATH = Path(__file__).parent.parent / "talon_settings.json"


def get_settings() -> Dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_settings(data: Dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))
