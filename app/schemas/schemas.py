"""Pydantic schemas for API request/response validation."""

from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel, Field


# ============================================================
# Match schemas
# ============================================================
class MatchBrief(BaseModel):
    match_id: str
    league: str
    home: str
    away: str
    kickoff_time: datetime
    match_date: date
    status: str
    actual_result: Optional[str] = None
    actual_score: Optional[str] = None


class MatchDetail(MatchBrief):
    cutoff_time: datetime
    is_focus_match: bool
    error_count: int
    created_at: datetime
    updated_at: datetime


# ============================================================
# Prediction schemas
# ============================================================
class FactorVoteSchema(BaseModel):
    factor_id: str
    factor_name: str
    vote: str = Field(..., description="主胜 / 平局 / 客胜")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    predicted_scores: Optional[list[str]] = None
    predicted_goals: Optional[int] = None
    predicted_half_full: Optional[list[str]] = None
    weight_used: Optional[float] = None
    note: Optional[str] = None


class PredictionResponse(BaseModel):
    prediction_id: str
    match_id: str
    version: str
    snapshot_type: str
    trigger_reason: str
    snapshot_time: datetime
    final_result: str
    final_score: Optional[list[str]] = None
    final_goals: Optional[int] = None
    final_half_full: Optional[list[str]] = None
    reasoning_summary: Optional[str] = None
    committee_details: list[dict] = []
    weights_used: dict = {}
    odds_snapshot: Optional[dict] = None
    has_risk_warning: bool = False
    risk_warning_text: Optional[str] = None


class PredictionHistoryResponse(BaseModel):
    snapshot_time: datetime
    trigger_reason: str
    final_result: str
    final_score: Optional[list[str]] = None
    final_goals: Optional[int] = None


# ============================================================
# Review schemas
# ============================================================
class ReviewReportResponse(BaseModel):
    match_id: str
    actual_result: str
    actual_score: str
    hit_result: bool
    hit_score: bool
    hit_goals: bool
    hit_half_full: bool
    v0_prediction: Optional[str] = None
    v_latest_prediction: Optional[str] = None
    prediction_shift: Optional[str] = None
    error_analysis: list[dict] = []
    weight_adjustment: dict = {}
    created_at: datetime


# ============================================================
# Factor / Weight schemas
# ============================================================
class FactorProfileResponse(BaseModel):
    factor_id: str
    name: str
    name_cn: str
    model: str
    specialization: str
    description: Optional[str] = None
    school: str
    is_active: bool


class FactorWeightResponse(BaseModel):
    factor_id: str
    league: str
    weight: float
    last_updated: datetime


# ============================================================
# Briefing schemas (Phase 2)
# ============================================================
class InjuryInfo(BaseModel):
    name: str
    pos: str
    status: str  # out / doubt / suspended
    confidence: str
    source: str


class FormData(BaseModel):
    last_3: list[str]
    venue: str
    confidence: str


class TeamStats(BaseModel):
    matches: int
    w: int
    d: int
    l: int
    gf_avg: float
    ga_avg: float
    confidence: str


class VerifiedBriefingResponse(BaseModel):
    match_id: str
    data_confidence: str
    content: dict
    odds_anchor: dict
    created_at: datetime


# ============================================================
# API common schemas
# ============================================================
class ApiResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: Optional[Any] = None


class PaginatedResponse(BaseModel):
    success: bool = True
    total: int = 0
    page: int = 1
    page_size: int = 20
    data: list[Any] = []


class TriggerPredictionRequest(BaseModel):
    force: bool = Field(False, description="Force regenerate even if within delta_t")
