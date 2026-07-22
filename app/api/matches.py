"""Match routes: list, detail, predictions, history, review."""

import logging
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.constants import MatchStatus, PredictionVersion
from app.core.state_machine import get_cutoff_time, is_locked
from app.models.models import (
    Match, Prediction, PredictionHistory, VerifiedBriefing,
    ReviewReport, OddsInitial,
)
from app.schemas.schemas import (
    MatchBrief, MatchDetail, PredictionResponse, PredictionHistoryResponse,
    ReviewReportResponse, ApiResponse, TriggerPredictionRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("", response_model=ApiResponse)
async def list_matches(
    status: Optional[str] = Query(None),
    league: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List matches with optional filters."""
    query = select(Match)

    if status:
        query = query.where(Match.status == status)
    if league:
        query = query.where(Match.league == league)
    if date_from:
        query = query.where(Match.match_date >= date.fromisoformat(date_from))
    if date_to:
        query = query.where(Match.match_date <= date.fromisoformat(date_to))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginate
    query = query.order_by(Match.kickoff_time.asc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    matches = result.scalars().all()

    return ApiResponse(
        success=True,
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                MatchBrief(
                    match_id=m.match_id, league=m.league, home=m.home, away=m.away,
                    kickoff_time=m.kickoff_time, match_date=m.match_date,
                    status=m.status, actual_result=m.actual_result, actual_score=m.actual_score,
                ).model_dump() for m in matches
            ]
        }
    )


@router.get("/{match_id}", response_model=ApiResponse)
async def get_match_detail(match_id: str, db: AsyncSession = Depends(get_db)):
    """Get match detail with prediction, briefing and review info."""
    result = await db.execute(select(Match).where(Match.match_id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Get V_latest prediction
    pred_result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match_id,
            Prediction.version == PredictionVersion.V_LATEST.value
        )
    )
    v_latest = pred_result.scalar_one_or_none()

    # Get V0 prediction
    v0_result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match_id,
            Prediction.version == PredictionVersion.V0.value
        )
    )
    v0 = v0_result.scalar_one_or_none()

    # Get review report
    review_result = await db.execute(
        select(ReviewReport).where(ReviewReport.match_id == match_id)
    )
    review = review_result.scalar_one_or_none()

    # Check lock status
    locked = is_locked(match.match_date)

    return ApiResponse(
        success=True,
        data={
            "match": MatchDetail(
                match_id=match.match_id, league=match.league, home=match.home,
                away=match.away, kickoff_time=match.kickoff_time,
                match_date=match.match_date, status=match.status,
                cutoff_time=match.cutoff_time, is_focus_match=match.is_focus_match,
                error_count=match.error_count, created_at=match.created_at,
                updated_at=match.updated_at,
                actual_result=match.actual_result, actual_score=match.actual_score,
            ).model_dump(),
            "is_locked": locked,
            "v_latest": PredictionResponse(
                prediction_id=v_latest.prediction_id, match_id=v_latest.match_id,
                version=v_latest.version, snapshot_type=v_latest.snapshot_type,
                trigger_reason=v_latest.trigger_reason, snapshot_time=v_latest.snapshot_time,
                final_result=v_latest.final_result, final_score=v_latest.final_score,
                final_goals=v_latest.final_goals, final_half_full=v_latest.final_half_full,
                reasoning_summary=v_latest.reasoning_summary,
                committee_details=v_latest.committee_details,
                weights_used=v_latest.weights_used,
                odds_snapshot=v_latest.odds_snapshot,
                has_risk_warning=v_latest.has_risk_warning,
                risk_warning_text=v_latest.risk_warning_text,
            ).model_dump() if v_latest else None,
            "v0": {
                "final_result": v0.final_result,
                "snapshot_time": v0.snapshot_time.isoformat(),
            } if v0 else None,
            "review": ReviewReportResponse(
                match_id=review.match_id, actual_result=review.actual_result,
                actual_score=review.actual_score,
                hit_result=review.hit_result, hit_score=review.hit_score,
                hit_goals=review.hit_goals, hit_half_full=review.hit_half_full,
                v0_prediction=review.v0_prediction,
                v_latest_prediction=review.v_latest_prediction,
                prediction_shift=review.prediction_shift,
                error_analysis=review.error_analysis,
                weight_adjustment=review.weight_adjustment,
                created_at=review.created_at,
            ).model_dump() if review else None,
        }
    )


@router.get("/{match_id}/predictions/history", response_model=ApiResponse)
async def get_prediction_history(match_id: str, db: AsyncSession = Depends(get_db)):
    """Get prediction history (Tab 2: 预测演变)."""
    result = await db.execute(
        select(PredictionHistory)
        .where(PredictionHistory.match_id == match_id)
        .order_by(PredictionHistory.snapshot_time.asc())
    )
    history = result.scalars().all()

    # Also include V0 and V_latest
    v0_result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match_id,
            Prediction.version == PredictionVersion.V0.value
        )
    )
    v0 = v0_result.scalar_one_or_none()

    v_latest_result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match_id,
            Prediction.version == PredictionVersion.V_LATEST.value
        )
    )
    v_latest = v_latest_result.scalar_one_or_none()

    timeline = []

    if v0:
        timeline.append({
            "version": "V0",
            "snapshot_time": v0.snapshot_time.isoformat(),
            "trigger_reason": v0.trigger_reason,
            "final_result": v0.final_result,
            "final_score": v0.final_score,
            "final_goals": v0.final_goals,
            "note": "初盘观点, 仅供参考, 非购彩建议"
        })

    for h in history:
        timeline.append({
            "version": "V_hist",
            "snapshot_time": h.snapshot_time.isoformat(),
            "trigger_reason": h.trigger_reason,
            "final_result": h.final_result,
            "final_score": h.final_score,
            "final_goals": h.final_goals,
        })

    if v_latest:
        timeline.append({
            "version": "V_latest",
            "snapshot_time": v_latest.snapshot_time.isoformat(),
            "trigger_reason": v_latest.trigger_reason,
            "final_result": v_latest.final_result,
            "final_score": v_latest.final_score,
            "final_goals": v_latest.final_goals,
        })

    return ApiResponse(success=True, data={"timeline": timeline})


@router.get("/{match_id}/briefing", response_model=ApiResponse)
async def get_briefing(match_id: str, db: AsyncSession = Depends(get_db)):
    """Get verified data briefing for a match."""
    result = await db.execute(
        select(VerifiedBriefing).where(VerifiedBriefing.match_id == match_id)
    )
    briefing = result.scalar_one_or_none()
    if not briefing:
        raise HTTPException(status_code=404, detail="Briefing not found")

    return ApiResponse(success=True, data={
        "match_id": briefing.match_id,
        "data_confidence": briefing.data_confidence,
        "content": briefing.content_json,
        "odds_anchor": briefing.odds_anchor,
        "created_at": briefing.created_at.isoformat(),
    })


@router.post("/{match_id}/trigger-prediction", response_model=ApiResponse)
async def trigger_prediction(
    match_id: str,
    request: TriggerPredictionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a new prediction for a match (user trigger)."""
    result = await db.execute(select(Match).where(Match.match_id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if is_locked(match.match_date) and not request.force:
        raise HTTPException(status_code=400, detail="Match is locked (past cutoff time)")

    from app.services.phase3_predict import run_phase3
    prediction = await run_phase3(db, match, trigger_reason="user")

    return ApiResponse(
        success=True,
        message="Prediction generated",
        data=PredictionResponse(
            prediction_id=prediction.prediction_id, match_id=prediction.match_id,
            version=prediction.version, snapshot_type=prediction.snapshot_type,
            trigger_reason=prediction.trigger_reason,
            snapshot_time=prediction.snapshot_time,
            final_result=prediction.final_result,
            final_score=prediction.final_score,
            final_goals=prediction.final_goals,
            final_half_full=prediction.final_half_full,
            reasoning_summary=prediction.reasoning_summary,
            committee_details=prediction.committee_details,
            weights_used=prediction.weights_used,
            odds_snapshot=prediction.odds_snapshot,
            has_risk_warning=prediction.has_risk_warning,
            risk_warning_text=prediction.risk_warning_text,
        ).model_dump() if prediction else None
    )
