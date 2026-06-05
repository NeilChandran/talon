"""Run once to seed default LinkedIn sequences and campaigns via Supabase."""
import asyncio
import uuid
from datetime import datetime

from store import get_store


DEFAULT_SEQUENCES = [
    {
        "id": str(uuid.uuid4()),
        "name": "Connect + Intro",
        "type": "connection_request",
        "connection_note_template": (
            "Hi {{first_name}}, love what you're building at {{company}}. "
            "Working on a tool for founders doing LinkedIn outreach — thought it might be relevant. "
            "Would love to connect!"
        ),
        "message_template": "",
        "subject_template": "",
        "body_template": "",
        "delay_days": 0,
        "created_at": datetime.utcnow().isoformat(),
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Follow-up Message",
        "type": "follow_up_message",
        "connection_note_template": "",
        "message_template": (
            "Hey {{first_name}}, thanks for connecting!\n\n"
            "I'm building Talon — AI that finds your ideal prospects on LinkedIn and automates outreach "
            "with personalised messages. Saves hours every week for founders doing outbound.\n\n"
            "Would love to show you a quick demo — any chance for a 15-min call this week?"
        ),
        "subject_template": "",
        "body_template": "",
        "delay_days": 3,
        "created_at": datetime.utcnow().isoformat(),
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Final Touch",
        "type": "final_message",
        "connection_note_template": "",
        "message_template": (
            "Hey {{first_name}}, one last note — if LinkedIn outreach is ever on your radar, "
            "Talon makes it effortless. Happy to share more whenever the timing's right. No pressure either way!"
        ),
        "subject_template": "",
        "body_template": "",
        "delay_days": 7,
        "created_at": datetime.utcnow().isoformat(),
    },
]


async def init():
    db = get_store()
    print("Connected to Supabase.")
    try:
        await db.list_sequences()
    except Exception as e:
        err = str(e)
        if "PGRST205" in err or "Could not find the table" in err:
            print(
                "Tables missing — run supabase/schema.sql in the Supabase SQL Editor first, "
                "then run init_db.py again."
            )
            return
        raise

    existing = await db.list_sequences()
    if not existing:
        for data in DEFAULT_SEQUENCES:
            await db.insert("sequences", data)
        print(f"Seeded {len(DEFAULT_SEQUENCES)} default LinkedIn sequences.")
    else:
        print(f"Sequences already exist ({len(existing)} found). Skipping seed.")
        print("Delete existing sequences to re-seed defaults.")

    campaigns = await db.list_campaigns(limit=1)
    if not campaigns:
        now = datetime.utcnow().isoformat()
        await db.insert(
            "campaigns",
            {
                "id": str(uuid.uuid4()),
                "name": "LinkedIn Outreach",
                "connection_note_template": (
                    "Hi {{first_name}} — I'm Neil, a Stanford student building Hedwig, "
                    "a free AI agent for Gmail and Google Calendar. Would love to connect!"
                ),
                "message_template": (
                    "Hey {{first_name}}, thanks for connecting!\n\n"
                    "Hedwig is a free AI agent that plugs into Gmail and Google Calendar — "
                    "it triages your inbox, drafts replies, and handles scheduling.\n\n"
                    "We have 500+ users from Stanford, DoorDash, and more. "
                    "Would love to show you a quick demo if you're open to it!"
                ),
                "wait_days_after_accept": 1,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        print("Seeded default LinkedIn Outreach campaign.")
    else:
        all_camps = await db.list_campaigns()
        print(f"Campaigns already exist ({len(all_camps)} found).")


if __name__ == "__main__":
    asyncio.run(init())
