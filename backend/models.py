import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.types import Uuid
from database import Base

# Cross-database types (SQLite local dev + PostgreSQL production)
UUID = Uuid


class Search(Base):
    """ICP prompt → Origami API → leads table."""
    __tablename__ = "searches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt = Column(Text, nullable=False)
    origami_job_id = Column(String(255), default="")  # agent_id:run_id
    status = Column(String(30), default="running")  # running | completed | failed | needs_input
    status_message = Column(String(500), default="Finding leads...")
    lead_count = Column(Integer, default=0)
    origami_table_id = Column(String(64), default="")
    origami_table_url = Column(String(500), default="")
    linkedin_message_template = Column(Text, default="")
    list_id = Column(UUID(as_uuid=True), ForeignKey("workspace_lists.id"), nullable=True)  # legacy
    created_at = Column(DateTime, default=datetime.utcnow)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id = Column(UUID(as_uuid=True), ForeignKey("searches.id"), nullable=True)
    first_name = Column(String(120), default="")
    last_name = Column(String(120), default="")
    name = Column(String(255))
    title = Column(String(255))
    company = Column(String(255))
    company_size = Column(String(50))
    email = Column(String(255))
    linkedin_url = Column(String(500))
    linkedin_profile_id = Column(String(255))   # ACoAAA... (for connection requests)
    linkedin_member_id = Column(String(100))     # numeric ID (for messaging)
    score = Column(Integer, default=5)
    icp_score = Column(Integer)  # legacy alias
    score_reason = Column(Text)
    source_url = Column(String(500), default="")
    sequence_status = Column(String(50), default="new")
    tech_stack = Column(JSON, default=list)
    status = Column(String(50), default="new")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Sequence(Base):
    __tablename__ = "sequences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255))
    type = Column(String(50))           # connection_request | follow_up_message | final_message
    # LinkedIn templates
    connection_note_template = Column(Text)   # ≤300 chars, for connection request
    message_template = Column(Text)           # follow-up message body
    # Legacy email fields kept for compat
    subject_template = Column(Text)
    body_template = Column(Text)
    delay_days = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class LinkedInOutreachLog(Base):
    __tablename__ = "linkedin_outreach_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id"))
    sequence_id = Column(UUID(as_uuid=True), ForeignKey("sequences.id"), nullable=True)
    outreach_type = Column(String(50))    # connection_request | message
    content = Column(Text)
    status = Column(String(50), default="pending")   # pending | sent | failed
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailSent(Base):
    __tablename__ = "emails_sent"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id"))
    sequence_id = Column(UUID(as_uuid=True), ForeignKey("sequences.id"))
    subject = Column(String(500))
    body = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)
    opened = Column(Boolean, default=False)
    replied = Column(Boolean, default=False)


class Workspace(Base):
    """Origami-style workspace — container for lists + campaigns."""
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    icon_letter = Column(String(2), default="T")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class WorkspaceList(Base):
    """A lead table inside a workspace (e.g. YC W26 Founders LinkedIn)."""
    __tablename__ = "workspace_lists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(255), nullable=False)
    icp_prompt = Column(Text, default="")
    status = Column(String(30), default="idle")  # idle | building | ready | failed
    build_step = Column(String(255), default="")
    row_count = Column(Integer, default=0)
    origami_meta = Column(JSON, default=dict)  # agentId, tableId, tableUrl, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class WorkspaceListLead(Base):
    """Lead row in a workspace list."""
    __tablename__ = "workspace_list_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_id = Column(UUID(as_uuid=True), ForeignKey("workspace_lists.id"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    first_name = Column(String(120), default="")
    last_name = Column(String(120), default="")
    title = Column(String(255), default="")
    company = Column(String(255), default="")
    linkedin_url = Column(String(500), default="")
    icp_score = Column(Integer, default=0)
    extra = Column(JSON, default=dict)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    """Multi-step LinkedIn outreach table (e.g. VC-Backed Founders LinkedIn)."""
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    list_id = Column(UUID(as_uuid=True), ForeignKey("workspace_lists.id"), nullable=True)
    search_id = Column(UUID(as_uuid=True), ForeignKey("searches.id"), nullable=True)
    name = Column(String(255), nullable=False)
    connection_note_template = Column(Text, default="")
    message_template = Column(Text, default="")
    wait_days_after_accept = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CampaignEnrollment(Base):
    """Per-lead state inside a campaign workflow."""
    __tablename__ = "campaign_enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False)
    # pending | connection_sent | accepted | dm_sent | replied | completed | stopped | failed
    status = Column(String(50), default="pending")
    connection_note = Column(Text)
    follow_up_message = Column(Text)
    connection_sent_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    dm_sent_at = Column(DateTime, nullable=True)
    stopped_reason = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AgentChatMessage(Base):
    __tablename__ = "agent_chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    list_id = Column(UUID(as_uuid=True), ForeignKey("workspace_lists.id"), nullable=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    role = Column(String(20))  # user | assistant
    content = Column(Text)
    suggested_actions = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExploreSession(Base):
    """Origami-style ICP explore session."""
    __tablename__ = "explore_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    icp_prompt = Column(Text, nullable=False)
    parsed_icp = Column(JSON, default=dict)
    status = Column(String(30), default="idle")  # idle | running | completed | failed
    scraper_status = Column(JSON, default=dict)
    filter_rules = Column(JSON, default=list)
    enrichment_columns = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ExploreRow(Base):
    __tablename__ = "explore_rows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("explore_sessions.id"), nullable=False)
    company_name = Column(String(255), nullable=False)
    website = Column(String(500), default="")
    industry = Column(String(255), default="")
    headcount = Column(String(50), default="")
    location = Column(String(255), default="")
    source = Column(String(50), default="")
    raw_data = Column(JSON, default=dict)
    fit_score = Column(Integer, default=0)
    enrichment = Column(JSON, default=dict)
    hidden = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExploreChatMessage(Base):
    __tablename__ = "explore_chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("explore_sessions.id"), nullable=False)
    role = Column(String(20))
    content = Column(Text)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
