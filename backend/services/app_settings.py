"""Persisted app settings (Instantly campaign ID, LinkedIn copy, etc.)."""
import json
from pathlib import Path
from typing import Any, Dict

SETTINGS_PATH = Path(__file__).parent.parent / "talon_settings.json"

HEDWIG_CONNECTION_DEFAULT = (
    "Hey {{first_name}}! I'm Neil, a Stanford student and Z Fellow building Hedwig, "
    "an AI-native inbox for Gmail + Google Calendar. It handles scheduling, follow-ups, "
    "drafting replies, and inbox organization. Free to use: hedwigmail.com. "
    "Thought it could fit well for you at {{company}}. Would love to connect."
)

HEDWIG_FOLLOW_UP_DEFAULT = (
    "Wanted to follow up here. Hedwig plugs directly into Gmail + Google Calendar and handles "
    "scheduling, follow-ups, inbox organization, and drafting replies in your tone.\n\n"
    "Teams across Stanford, Harvard, Yale, Berkeley, and UCLA have been using it heavily already, "
    "along with people from YC, a16z, and Pear portfolio companies. No migration or workflow "
    "change required. Completely free to use right now at hedwigmail.com - would love your thoughts."
)


def get_settings() -> Dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_settings(data: Dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


def get_linkedin_message_templates() -> Dict[str, str]:
    s = get_settings()
    conn = (s.get("linkedin_connection_template") or "").strip()
    follow = (s.get("linkedin_follow_up_template") or "").strip()
    return {
        "connection": conn or HEDWIG_CONNECTION_DEFAULT,
        "follow_up": follow or HEDWIG_FOLLOW_UP_DEFAULT,
    }
