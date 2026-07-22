"""Monitor & admin routes: factor weights, provider status, error logs, params."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.constants import FACTOR_DEFINITIONS, ERROR_TAXONOMY, BASE_WEIGHTS
from app.models.models import FactorWeight, ErrorLog, FactorProfile, ModelParam
from app.providers.registry import get_provider_status
from app.schemas.schemas import ApiResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/dashboard", response_model=ApiResponse)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Dashboard overview: hit rate, factor weights, status summary."""
    from app.models.models import Match, ReviewReport, Prediction
    from app.core.constants import MatchStatus, PredictionVersion
    from sqlalchemy import func

    # Count matches by status
    status_counts = {}
    for status in MatchStatus:
        result = await db.execute(
            select(func.count()).select_from(Match).where(Match.status == status.value)
        )
        status_counts[status.value] = result.scalar()

    # Hit rate
    total_reviews = await db.execute(
        select(func.count()).select_from(ReviewReport)
    )
    total_r = total_reviews.scalar()
    hits = await db.execute(
        select(func.count()).select_from(ReviewReport).where(ReviewReport.hit_result == True)
    )
    hit_count = hits.scalar()
    hit_rate = (hit_count / total_r * 100) if total_r and total_r > 0 else 0

    # Factor weights per league
    weights_result = await db.execute(select(FactorWeight))
    all_weights = weights_result.scalars().all()

    # Group by league
    weights_by_league = {}
    for w in all_weights:
        if w.league not in weights_by_league:
            weights_by_league[w.league] = {}
        weights_by_league[w.league][w.factor_id] = w.weight

    return ApiResponse(success=True, data={
        "status_counts": status_counts,
        "hit_rate": {
            "total_reviews": total_r,
            "hits": hit_count,
            "rate": round(hit_rate, 2),
        },
        "factor_weights": weights_by_league,
        "base_weights": BASE_WEIGHTS,
    })


@router.get("/factors", response_model=ApiResponse)
async def get_factors(db: AsyncSession = Depends(get_db)):
    """List all factor profiles and their current provider status."""
    provider_status = get_provider_status()

    factors = []
    for factor_id, defn in FACTOR_DEFINITIONS.items():
        # Get DB profile if exists
        result = await db.execute(
            select(FactorProfile).where(FactorProfile.factor_id == factor_id)
        )
        profile = result.scalar_one_or_none()

        factors.append({
            "factor_id": factor_id,
            "name": defn["name"],
            "name_cn": defn["name_cn"],
            "model": defn["model"],
            "specialization": defn["specialization"],
            "description": defn["description"],
            "school": defn["school"],
            "is_active": profile.is_active if profile else True,
            "provider_info": provider_status.get(factor_id, {}),
        })

    return ApiResponse(success=True, data=factors)


@router.get("/weights", response_model=ApiResponse)
async def get_factor_weights(
    league: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get factor weights, optionally filtered by league."""
    query = select(FactorWeight)
    if league:
        query = query.where(FactorWeight.league == league)

    result = await db.execute(query.order_by(FactorWeight.league, FactorWeight.factor_id))
    weights = result.scalars().all()

    return ApiResponse(success=True, data=[
        {
            "factor_id": w.factor_id,
            "league": w.league,
            "weight": w.weight,
            "last_updated": w.last_updated.isoformat(),
        }
        for w in weights
    ])


@router.get("/errors", response_model=ApiResponse)
async def get_error_logs(
    error_code: str = Query(None),
    factor_id: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List error logs with optional filters."""
    query = select(ErrorLog)
    if error_code:
        query = query.where(ErrorLog.error_code == error_code)
    if factor_id:
        query = query.where(ErrorLog.factor_id == factor_id)

    query = query.order_by(ErrorLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return ApiResponse(success=True, data=[
        {
            "id": log.id,
            "match_id": log.match_id,
            "error_code": log.error_code,
            "factor_id": log.factor_id,
            "description": log.description,
            "stage": log.stage,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ])


@router.get("/error-taxonomy", response_model=ApiResponse)
async def get_error_taxonomy():
    """Get the full error taxonomy (E001-E008)."""
    return ApiResponse(success=True, data=ERROR_TAXONOMY)


@router.get("/params", response_model=ApiResponse)
async def get_model_params(db: AsyncSession = Depends(get_db)):
    """Get model hyperparameters."""
    result = await db.execute(select(ModelParam))
    params = result.scalars().all()

    # Include defaults from settings if not in DB
    from app.config import settings
    defaults = {
        "delta_t": settings.delta_t,
        "volatility_threshold": settings.volatility_threshold,
        "learning_rate": settings.learning_rate,
        "max_history": settings.max_history,
    }

    db_params = {p.param_name: p.value for p in params}

    return ApiResponse(success=True, data={
        "defaults": defaults,
        "overrides": db_params,
    })


@router.put("/params/{param_name}", response_model=ApiResponse)
async def update_model_param(
    param_name: str,
    value: str,
    db: AsyncSession = Depends(get_db),
):
    """Update a model hyperparameter."""
    result = await db.execute(select(ModelParam).where(ModelParam.param_name == param_name))
    param = result.scalar_one_or_none()

    if param:
        param.value = value
    else:
        param = ModelParam(param_name=param_name, value=value)
        db.add(param)

    await db.commit()
    return ApiResponse(success=True, message=f"Updated {param_name} = {value}")
