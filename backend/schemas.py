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


# ─── Campaigns (origami-style workspace) ─────────────────────────────────────

class CampaignBase(BaseModel):
    name: str
    connection_note_template: Optional[str] = ""
    message_template: Optional[str] = ""
    wait_days_after_accept: int = 1
    is_active: bool = True


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    connection_note_template: Optional[str] = None
    message_template: Optional[str] = None
    wait_days_after_accept: Optional[int] = None
    is_active: Optional[bool] = None


class CampaignResponse(CampaignBase):
    id: UUID4
    enrollment_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EnrollmentStatus(str, Enum):
    pending = "pending"
    connection_sent = "connection_sent"
    accepted = "accepted"
    dm_sent = "dm_sent"
    replied = "replied"
    completed = "completed"
    stopped = "stopped"
    failed = "failed"


class CampaignEnrollmentResponse(BaseModel):
    id: UUID4
    campaign_id: UUID4
    lead_id: UUID4
    status: str
    connection_note: Optional[str] = None
    follow_up_message: Optional[str] = None
    connection_sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    dm_sent_at: Optional[datetime] = None
    stopped_reason: Optional[str] = None
    last_error: Optional[str] = None
    # Lead fields for UI
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    linkedin_url: Optional[str] = None
    lead_status: Optional[str] = None

    class Config:
        from_attributes = True


class EnrollLeadsRequest(BaseModel):
    lead_ids: Optional[List[UUID4]] = None  # None = enroll all leads with LinkedIn URL


class AgentChatRequest(BaseModel):
    message: str
    campaign_id: Optional[UUID4] = None


class SuggestedAction(BaseModel):
    id: str
    label: str
    action: str  # launch_campaign | update_copy | check_replies | enroll_leads


class AgentChatResponse(BaseModel):
    reply: str
    suggested_actions: List[SuggestedAction] = []
    campaign_updated: bool = False


# ─── Explore (Origami-style) ───────────────────────────────────────────────────

class ExploreSessionCreate(BaseModel):
    icp_prompt: str


class ExploreRowUpdate(BaseModel):
    company_name: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    headcount: Optional[str] = None
    location: Optional[str] = None


class ExploreRefineRequest(BaseModel):
    message: str


class ExploreFilterRule(BaseModel):
    field: str
    op: str = "contains"
    value: str


class ExploreEnrichRequest(BaseModel):
    column_key: str
    column_type: str  # work_email | phone | tech_stack | funding | decision_maker_linkedin


class ExploreRowResponse(BaseModel):
    id: UUID4
    company_name: str
    website: str = ""
    industry: str = ""
    headcount: str = ""
    location: str = ""
    source: str = ""
    fit_score: int = 0
    enrichment: dict = {}
    hidden: bool = False

    class Config:
        from_attributes = True


class ExploreSessionResponse(BaseModel):
    id: UUID4
    icp_prompt: str
    parsed_icp: dict = {}
    status: str
    scraper_status: dict = {}
    filter_rules: list = []
    enrichment_columns: list = []
    rows: List[ExploreRowResponse] = []
    messages: list = []
    created_at: datetime

    class Config:
        from_attributes = True
