from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Request Models ──────────────────────────────────────────────────────────

class TextAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50_000, description="Text to analyze for bias")
    categories: list[str] = Field(
        default=["gender", "race", "age", "disability"],
        description="Bias categories to check",
    )


class DatasetAnalysisRequest(BaseModel):
    data: list[dict] = Field(..., min_length=1, max_length=10_000, description="Dataset rows as list of dicts")
    target_column: str = Field(..., description="Name of the outcome/target column")
    protected_columns: list[str] = Field(..., min_length=1, description="Protected attribute columns")


# ── Response Models ─────────────────────────────────────────────────────────

class FlaggedPhrase(BaseModel):
    phrase: str
    start: int
    end: int
    category: str
    severity: str = Field(description="low, medium, or high")
    suggestion: str = Field(default="", description="Suggested alternative")


class BiasScore(BaseModel):
    category: str
    score: float = Field(ge=0, le=100, description="0-100, where 100 = no bias detected")
    confidence: float = Field(ge=0, le=1, description="Confidence in the score")
    flagged_phrases: list[FlaggedPhrase]


class FairnessReport(BaseModel):
    report_id: str
    overall_score: float = Field(ge=0, le=100)
    bias_scores: list[BiasScore]
    recommendations: list[str]
    text_length: int
    categories_analyzed: list[str]
    timestamp: datetime
    provenance_receipt: Optional["ProvenanceReceipt"] = Field(
        default=None,
        description="CPL receipt proving which community standard governed this analysis",
    )


class GroupOutcome(BaseModel):
    group: str
    positive_rate: float
    count: int


class ProtectedColumnReport(BaseModel):
    column: str
    disparate_impact_ratio: float = Field(description="Ratio of min/max positive rates (>0.8 = passes 80% rule)")
    statistical_parity_difference: float = Field(description="Max difference in positive rates between groups")
    equal_opportunity_difference: float = Field(description="Difference in positive rates for best vs worst group")
    group_outcomes: list[GroupOutcome]
    passes_four_fifths_rule: bool


class DatasetFairnessReport(BaseModel):
    report_id: str
    overall_fairness_score: float = Field(ge=0, le=100)
    total_rows: int
    target_column: str
    protected_columns_analysis: list[ProtectedColumnReport]
    recommendations: list[str]
    timestamp: datetime
    provenance_receipt: Optional["ProvenanceReceipt"] = Field(
        default=None,
        description="CPL receipt proving which community standard governed this analysis",
    )


# ── API Key & Usage Models ──────────────────────────────────────────────────

class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Friendly name for the key")


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str = Field(description="First 12 characters of the key for identification")
    created_at: datetime
    is_active: bool


class APIKeyCreated(BaseModel):
    id: int
    name: str
    api_key: str = Field(description="Full API key - store it securely, it won't be shown again")
    created_at: datetime


class UsageResponse(BaseModel):
    tier: str
    monthly_limit: int
    used_this_month: int
    remaining: int
    period_start: datetime
    period_end: datetime


# ── Billing Models ──────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str = Field(..., pattern="^(pro|enterprise)$", description="Plan to subscribe to")
    success_url: str = Field(..., description="URL to redirect on success")
    cancel_url: str = Field(..., description="URL to redirect on cancel")


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


# ── User Models ─────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str = Field(..., description="User email address")


class UserResponse(BaseModel):
    id: int
    email: str
    tier: str
    created_at: datetime


# ── Racial Fairness Models (merged from adaptive-racial-fairness-framework) ──

class RacialAuditRequest(BaseModel):
    data: list[dict] = Field(..., min_length=1, max_length=10_000, description="Dataset rows")
    race_col: str = Field(..., description="Sensitive attribute column")
    outcome_col: str = Field(..., description="Outcome column")
    favorable_value: str = Field(..., description="Value representing favorable outcome")
    privileged_group: Optional[str] = Field(default=None, description="Reference group (default: White)")


class ReweightRequest(BaseModel):
    data: list[dict] = Field(..., min_length=1, max_length=10_000)
    race_col: str
    outcome_col: str
    favorable_value: str


class DebiasRequest(BaseModel):
    data: list[dict] = Field(..., min_length=1, max_length=10_000)
    race_col: str
    outcome_col: str
    favorable_value: str
    feature_cols: list[str] = Field(..., min_length=1)
    constraint: str = Field(default="demographic_parity")


class CommunityConfigCreate(BaseModel):
    priority_groups: list[str] = Field(..., min_length=1)
    fairness_target: str
    fairness_threshold: float = Field(default=0.8, gt=0, le=1)
    input_protocol: str = Field(default="community_session")
    input_location: str = Field(default="")
    input_participants: int = Field(default=0, ge=0)
    facilitator: str = Field(default="")
    notes: str = Field(default="")


# ── Provenance Ledger Models ───────────────────────────────────────────────

class DemographicSummary(BaseModel):
    """Aggregated, anonymous demographic snapshot — NO PII."""
    majority_race: str = Field(..., description="Largest racial/ethnic group, e.g. 'Black'")
    majority_race_pct: float = Field(..., ge=0, le=100, description="Percentage of majority group")
    median_age: int = Field(..., ge=0, description="Median age of participants")
    additional: dict = Field(default_factory=dict, description="Extra aggregated fields (gender_split, etc.)")


class ProvenanceLedgerCreate(BaseModel):
    """Input for creating a CPL entry. Strictly anonymous — no names, IPs, or PII."""
    council_label: str = Field(..., min_length=1, max_length=128, description="Session identifier, e.g. 'Council 4A'")
    participant_count: int = Field(..., ge=1, description="Number of session participants")
    demographic_summary: DemographicSummary
    consensus_summary: str = Field(
        ..., min_length=10, max_length=2000,
        description="Qualitative summary of community consensus — no individual names",
    )
    input_protocol: str = Field(default="community_session")
    community_config_id: int = Field(..., description="ID of the CommunityConfig this session produced")


class ProvenanceLedgerResponse(BaseModel):
    id: int
    entry_hash: str = Field(description="SHA-256 hash binding session metadata to quantitative output")
    prev_hash: Optional[str] = Field(description="Hash of predecessor entry (None for genesis)")
    council_label: str
    participant_count: int
    demographic_summary: DemographicSummary
    consensus_summary: str
    input_protocol: str
    fairness_threshold: str
    priority_groups: list[str]
    fairness_target: str
    created_at: datetime


class ProvenanceReceipt(BaseModel):
    """
    Lightweight receipt embedded in every analysis response.
    Proves which community standard governed the analysis and lets
    auditors independently verify the hash chain.
    """
    ledger_hash: str = Field(description="SHA-256 hash of the governing CPL entry")
    prev_hash: Optional[str] = Field(description="Predecessor hash for chain verification")
    council_label: str
    participant_count: int
    demographic_summary: DemographicSummary
    consensus_summary: str
    fairness_threshold: float
    priority_groups: list[str]
    fairness_target: str
    governed_at: datetime = Field(description="When the CPL entry was created")
