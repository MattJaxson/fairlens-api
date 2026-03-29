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
