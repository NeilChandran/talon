from pydantic import BaseModel
from pydantic import UUID4
from datetime import datetime
from typing import Optional, List
from enum import Enum


class LeadStatus(str, Enum):
    new = "new"
    contacted = "contacted"
    replied = "replied"
    closed = "closed"


class LeadBase(BaseModel):
    name: str
    title: Optional[str] = None
    company: Optional[str] = None
    company_size: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    linkedin_profile_id: Optional[str] = None
    linkedin_member_id: Optional[str] = None
    icp_score: Optional[int] = None
    score_reason: Optional[str] = None
    tech_stack: Optional[List[str]] = []
    status: LeadStatus = LeadStatus.new


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    company_size: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    linkedin_profile_id: Optional[str] = None
    linkedin_member_id: Optional[str] = None
    icp_score: Optional[int] = None
    score_reason: Optional[str] = None
    tech_stack: Optional[List[str]] = None
    status: Optional[LeadStatus] = None


class LeadResponse(LeadBase):
    id: UUID4
    created_at: datetime

    class Config:
        from_attributes = True


class SequenceType(str, Enum):
    connection_request = "connection_request"
    follow_up_message = "follow_up_message"
    final_message = "final_message"


class SequenceBase(BaseModel):
    name: str
    type: SequenceType
    connection_note_template: Optional[str] = ""
    message_template: Optional[str] = ""
    subject_template: Optional[str] = ""
    body_template: Optional[str] = ""
    delay_days: int = 0


class SequenceCreate(SequenceBase):
    pass


class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    connection_note_template: Optional[str] = None
    message_template: Optional[str] = None
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    delay_days: Optional[int] = None


class SequenceResponse(SequenceBase):
    id: UUID4
    created_at: datetime

    class Config:
        from_attributes = True


class ProspectingRequest(BaseModel):
    query: str


class GenerateLinkedInRequest(BaseModel):
    lead_ids: List[UUID4]
    sequence_type: str = "connection_request"


class RunSequenceRequest(BaseModel):
    lead_ids: List[UUID4]
    sequence_id: UUID4


class GenerateEmailRequest(BaseModel):
    lead_ids: List[UUID4]
    sequence_id: UUID4


class SendEmailRequest(BaseModel):
    lead_id: UUID4
    sequence_id: UUID4
    subject: str
    body: str


class StatsResponse(BaseModel):
    total_leads: int
    emails_sent: int
    reply_rate: float
    leads_this_week: int
