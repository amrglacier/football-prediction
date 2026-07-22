"""Admin routes: manual pipeline triggers, config management."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.constants import MatchStatus, DEFAULT_LEAGUES
from app.core.settings_db import get_league_config, set_league_config, get_league_whitelist
from app.models.models import Match
from app.schemas.schemas import ApiResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/fetch-fixtures", response_model=ApiResponse)
async def trigger_fetch_fixtures(
    target_date: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger Phase 1: fetch fixtures using DB league whitelist."""
    from app.services.phase1_selection import run_phase1

    d = date.fromisoformat(target_date) if target_date else date.today()
    leagues = await get_league_whitelist(db)
    matches = await run_phase1(db, target_date=d, leagues=leagues)

    return ApiResponse(
        success=True,
        message=f"Fetched {len(matches)} matches for {d}",
        data={"match_count": len(matches), "date": str(d), "leagues_used": leagues}
    )


@router.post("/matches/{match_id}/acquire-data", response_model=ApiResponse)
async def trigger_acquire_data(match_id: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger Phase 2: acquire data for a match."""
    from app.services.phase2_data import run_phase2

    result = await db.execute(select(Match).where(Match.match_id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    briefing = await run_phase2(db, match)

    return ApiResponse(
        success=True,
        message=f"Data acquired for {match_id}",
        data={"match_id": match_id, "confidence": briefing.data_confidence}
    )


@router.post("/matches/{match_id}/predict", response_model=ApiResponse)
async def trigger_predict(match_id: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger Phase 3: generate prediction."""
    from app.services.phase3_predict import run_phase3

    result = await db.execute(select(Match).where(Match.match_id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    prediction = await run_phase3(db, match, trigger_reason="user")

    return ApiResponse(
        success=True,
        message=f"Prediction generated for {match_id}",
        data={"prediction_id": prediction.prediction_id if prediction else None}
    )


@router.post("/matches/{match_id}/review", response_model=ApiResponse)
async def trigger_review(match_id: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger Phase 4: review a match."""
    from app.services.phase4_review import run_phase4

    result = await db.execute(select(Match).where(Match.match_id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    report = await run_phase4(db, match)

    return ApiResponse(
        success=True,
        message=f"Review completed for {match_id}",
        data={"hit_result": report.hit_result if report else None}
    )


@router.get("/leagues", response_model=ApiResponse)
async def get_league_whitelist_endpoint(db: AsyncSession = Depends(get_db)):
    """Get current league whitelist configuration."""
    config = await get_league_config(db)
    active = [league for league, enabled in config.items() if enabled]
    return ApiResponse(success=True, data={
        "config": config,
        "active_leagues": active,
    })


@router.put("/leagues", response_model=ApiResponse)
async def update_league_whitelist(
    config: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update league whitelist configuration."""
    await set_league_config(db, config)
    active = [league for league, enabled in config.items() if enabled]
    return ApiResponse(
        success=True,
        message=f"Updated league whitelist. Active: {', '.join(active)}",
        data={"config": config, "active_leagues": active}
    )


@router.get("/health", response_model=ApiResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """System health check."""
    from app.providers.registry import get_provider_status

    providers = get_provider_status()
    leagues = await get_league_whitelist(db)

    return ApiResponse(success=True, data={
        "status": "running",
        "providers": providers,
        "active_leagues": leagues,
    })
