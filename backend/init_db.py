"""Run once to create tables and seed default LinkedIn sequences."""
import asyncio
import uuid
from datetime import datetime

from database import AsyncSessionLocal, Base, engine
from models import (  # noqa
    Lead,
    Sequence,
    EmailSent,
    LinkedInOutreachLog,
    Search,
    Workspace,
    WorkspaceList,
    WorkspaceListLead,
    Campaign,
    CampaignEnrollment,
    AgentChatMessage,
    ExploreSession,
    ExploreRow,
    ExploreChatMessage,
)


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

    # SQLite-safe column migrations (no IF NOT EXISTS on older SQLite)
    from sqlalchemy import text

    async def _add_col(conn, table: str, col: str, typedef: str):
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
        except Exception:
            pass

    async with engine.begin() as conn:
        for table, col, typedef in [
            ("leads", "linkedin_profile_id", "VARCHAR(255)"),
            ("leads", "linkedin_member_id", "VARCHAR(100)"),
            ("sequences", "connection_note_template", "TEXT"),
            ("sequences", "message_template", "TEXT"),
            ("campaigns", "workspace_id", "CHAR(32)"),
            ("campaigns", "list_id", "CHAR(32)"),
            ("campaigns", "search_id", "CHAR(32)"),
            ("agent_chat_messages", "workspace_id", "CHAR(32)"),
            ("agent_chat_messages", "list_id", "CHAR(32)"),
            ("leads", "search_id", "CHAR(32)"),
            ("leads", "first_name", "VARCHAR(120)"),
            ("leads", "last_name", "VARCHAR(120)"),
            ("leads", "source_url", "VARCHAR(500)"),
            ("leads", "sequence_status", "VARCHAR(50)"),
            ("workspace_lists", "origami_meta", "TEXT"),
            ("searches", "origami_job_id", "VARCHAR(255)"),
            ("searches", "status_message", "VARCHAR(500)"),
            ("searches", "lead_count", "INTEGER"),
            ("searches", "origami_table_id", "VARCHAR(64)"),
            ("searches", "origami_table_url", "VARCHAR(500)"),
            ("searches", "linkedin_message_template", "TEXT"),
            ("leads", "score", "INTEGER"),
        ]:
            await _add_col(conn, table, col, typedef)
        print("Column migrations applied.")

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

    # Seed default campaign if none exist
    async with AsyncSessionLocal() as session:
        camp_result = await session.execute(select(Campaign))
        camps = camp_result.scalars().all()
        if not camps:
            default_campaign = Campaign(
                id=uuid.uuid4(),
                name="LinkedIn Outreach",
                connection_note_template=(
                    "Hi {{first_name}} — I'm Neil, a Stanford student building Hedwig, "
                    "a free AI agent for Gmail and Google Calendar. Would love to connect!"
                ),
                message_template=(
                    "Hey {{first_name}}, thanks for connecting!\n\n"
                    "Hedwig is a free AI agent that plugs into Gmail and Google Calendar — "
                    "it triages your inbox, drafts replies, and handles scheduling.\n\n"
                    "We have 500+ users from Stanford, DoorDash, and more. "
                    "Would love to show you a quick demo if you're open to it!"
                ),
                wait_days_after_accept=1,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(default_campaign)
            await session.commit()
            print("Seeded default LinkedIn Outreach campaign.")
        else:
            print(f"Campaigns already exist ({len(camps)} found).")


if __name__ == "__main__":
    asyncio.run(init())
