"""Run once to create tables and seed default LinkedIn sequences."""
import asyncio
import uuid
from datetime import datetime

from database import AsyncSessionLocal, Base, engine
from models import Lead, Sequence, EmailSent, LinkedInOutreachLog  # noqa


DEFAULT_SEQUENCES = [
    {
        "id": uuid.uuid4(),
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
        "created_at": datetime.utcnow(),
    },
    {
        "id": uuid.uuid4(),
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
        "created_at": datetime.utcnow(),
    },
    {
        "id": uuid.uuid4(),
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
        "created_at": datetime.utcnow(),
    },
]


async def init():
    # Create all tables (no-op if they exist)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created/verified.")

    # Add new LinkedIn columns if missing (safe migration)
    async with engine.begin() as conn:
        try:
            await conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_profile_id VARCHAR(255)"
                )
            )
            await conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_member_id VARCHAR(100)"
                )
            )
            await conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE sequences ADD COLUMN IF NOT EXISTS connection_note_template TEXT"
                )
            )
            await conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE sequences ADD COLUMN IF NOT EXISTS message_template TEXT"
                )
            )
            print("LinkedIn columns added/verified.")
        except Exception as e:
            print(f"Column migration note: {e}")

    # Seed default sequences if none exist
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        result = await session.execute(select(Sequence))
        existing = result.scalars().all()

        if not existing:
            for data in DEFAULT_SEQUENCES:
                session.add(Sequence(**data))
            await session.commit()
            print(f"Seeded {len(DEFAULT_SEQUENCES)} default LinkedIn sequences.")
        else:
            print(f"Sequences already exist ({len(existing)} found). Skipping seed.")
            print("Delete existing sequences to re-seed defaults.")


if __name__ == "__main__":
    asyncio.run(init())
