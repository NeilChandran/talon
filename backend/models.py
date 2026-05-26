import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from database import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255))
    title = Column(String(255))
    company = Column(String(255))
    company_size = Column(String(50))
    email = Column(String(255))
    linkedin_url = Column(String(500))
    linkedin_profile_id = Column(String(255))   # ACoAAA... (for connection requests)
    linkedin_member_id = Column(String(100))     # numeric ID (for messaging)
    icp_score = Column(Integer)
    score_reason = Column(Text)
    tech_stack = Column(ARRAY(String), default=[])
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
