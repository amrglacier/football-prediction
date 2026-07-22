"""SQLAlchemy ORM models for all 10 database tables.

Tables (per spec section 5.1):
  1. Match          - match master
  2. OddsInitial    - initial odds snapshot
  3. VerifiedBriefing - verified data briefing (Phase 2 output)
  4. Prediction     - predictions (V0 / V_latest)
  5. PredictionHistory - rolling prediction history (max 5)
  6. FactorProfile  - factor archive / config
  7. FactorWeight   - dynamic weights per factor per league
  8. ErrorLog       - error logs
  9. ModelParam     - model hyperparameters
 10. ReviewReport   - post-match review reports (Phase 4)
"""

import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, Date, JSON,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ============================================================
# 1. Match - match master table
# ============================================================
class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    league: Mapped[str] = mapped_column(String(64), index=True)
    home: Mapped[str] = mapped_column(String(128))
    away: Mapped[str] = mapped_column(String(128))
    kickoff_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    match_date: Mapped[date] = mapped_column(Date, index=True)
    cutoff_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="SCHEDULED", index=True)

    # Actual result (filled after match ends)
    actual_result: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    actual_score: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Metadata
    is_focus_match: Mapped[bool] = mapped_column(Boolean, default=False)
    api_fixture_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    odds_initial: Mapped[Optional["OddsInitial"]] = relationship(back_populates="match", uselist=False)
    briefing: Mapped[Optional["VerifiedBriefing"]] = relationship(back_populates="match", uselist=False)
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="match")

    __table_args__ = (
        Index("ix_matches_league_date", "league", "match_date"),
    )


# ============================================================
# 2. OddsInitial - initial odds snapshot
# ============================================================
class OddsInitial(Base):
    __tablename__ = "odds_initial"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[str] = mapped_column(String(64), ForeignKey("matches.match_id"), index=True)
    h: Mapped[float] = mapped_column(Float)    # home win odds
    d: Mapped[float] = mapped_column(Float)    # draw odds
    a: Mapped[float] = mapped_column(Float)    # away win odds
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    match: Mapped["Match"] = relationship(back_populates="odds_initial")


# ============================================================
# 3. VerifiedBriefing - Phase 2 verified data briefing
# ============================================================
class VerifiedBriefing(Base):
    __tablename__ = "verified_briefing"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[str] = mapped_column(String(64), ForeignKey("matches.match_id"), index=True)
    data_confidence: Mapped[str] = mapped_column(String(16), default="medium")
    content_json: Mapped[dict] = mapped_column(JSON)        # full briefing content
    odds_anchor: Mapped[dict] = mapped_column(JSON)          # {snapshot_time, h, d, a}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    match: Mapped["Match"] = relationship(back_populates="briefing")


# ============================================================
# 4. Prediction - V0 / V_latest predictions
# ============================================================
class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[str] = mapped_column(String(64), ForeignKey("matches.match_id"), index=True)
    version: Mapped[str] = mapped_column(String(16), index=True)  # V0 / V_latest
    snapshot_type: Mapped[str] = mapped_column(String(16))         # V0 / V_latest
    trigger_reason: Mapped[str] = mapped_column(String(32))
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Final prediction result
    final_result: Mapped[str] = mapped_column(String(16))    # 主胜 / 平局 / 客胜
    final_score: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    final_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_half_full: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    reasoning_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Committee details and weights
    committee_details: Mapped[list] = mapped_column(JSON, default=list)
    weights_used: Mapped[dict] = mapped_column(JSON, default=dict)
    odds_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    odds_snapshot_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Risk warning
    has_risk_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_warning_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    match: Mapped["Match"] = relationship(back_populates="predictions")

    __table_args__ = (
        UniqueConstraint("match_id", "version", name="uq_prediction_match_version"),
    )


# ============================================================
# 5. PredictionHistory - rolling storage (max 5 recent)
# ============================================================
class PredictionHistory(Base):
    __tablename__ = "prediction_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[str] = mapped_column(String(64), ForeignKey("matches.match_id"), index=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    trigger_reason: Mapped[str] = mapped_column(String(32))
    final_result: Mapped[str] = mapped_column(String(16))
    final_score: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    final_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    committee_details: Mapped[list] = mapped_column(JSON, default=list)
    weights_used: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_pred_history_match_time", "match_id", "snapshot_time"),
    )


# ============================================================
# 6. FactorProfile - factor archive / configuration
# ============================================================
class FactorProfile(Base):
    __tablename__ = "factor_profiles"

    factor_id: Mapped[str] = mapped_column(String(8), primary_key=True)   # F1-F8
    name: Mapped[str] = mapped_column(String(64))
    name_cn: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    specialization: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    school: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    prompt_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# 7. FactorWeight - dynamic weights per factor per league
# ============================================================
class FactorWeight(Base):
    __tablename__ = "factor_weights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    factor_id: Mapped[str] = mapped_column(String(8), index=True)
    league: Mapped[str] = mapped_column(String(64), index=True)
    weight: Mapped[float] = mapped_column(Float)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("factor_id", "league", name="uq_factor_league"),
    )


# ============================================================
# 8. ErrorLog - error logs
# ============================================================
class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    error_code: Mapped[str] = mapped_column(String(8), index=True)
    factor_id: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # phase1-4
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ============================================================
# 9. ModelParam - model hyperparameters
# ============================================================
class ModelParam(Base):
    __tablename__ = "model_params"

    param_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# 10. ReviewReport - post-match review (Phase 4 output)
# ============================================================
class ReviewReport(Base):
    __tablename__ = "review_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[str] = mapped_column(String(64), ForeignKey("matches.match_id"), index=True)
    actual_result: Mapped[str] = mapped_column(String(16))
    actual_score: Mapped[str] = mapped_column(String(16))

    # Hit status
    hit_result: Mapped[bool] = mapped_column(Boolean)
    hit_score: Mapped[bool] = mapped_column(Boolean)
    hit_goals: Mapped[bool] = mapped_column(Boolean)
    hit_half_full: Mapped[bool] = mapped_column(Boolean)

    # Predictions compared
    v0_prediction: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    v_latest_prediction: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    prediction_shift: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Error analysis
    error_analysis: Mapped[list] = mapped_column(JSON, default=list)

    # Weight adjustment
    weight_adjustment: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
