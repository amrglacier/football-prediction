"""Main FastAPI application factory."""

import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.config import settings
from app.core.database import init_db, async_session_factory
from app.core.constants import MatchStatus
from app.core.state_machine import is_locked
from app.models.models import Match
from app.api.matches import router as matches_router
from app.api.monitor import router as monitor_router
from app.api.admin import router as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _pipeline_loop():
    """Background pipeline loop - replaces Celery for lightweight mode.

    Runs every 60 seconds, checks all matches and advances their state.
    """
    from app.services.phase2_data import run_phase2
    from app.services.phase3_predict import run_phase3, check_volatility
    from app.services.phase4_review import run_phase4

    while True:
        try:
            await asyncio.sleep(60)
            async with async_session_factory() as db:
                now = datetime.utcnow()
                result = await db.execute(
                    select(Match).where(
                        Match.status.in_([
                            MatchStatus.SCHEDULED.value,
                            MatchStatus.DATA_READY.value,
                            MatchStatus.PREDICTED.value,
                            MatchStatus.LOCKED.value,
                            MatchStatus.FINISHED.value,
                        ])
                    )
                )
                matches = result.scalars().all()

                for match in matches:
                    try:
                        if match.status == MatchStatus.SCHEDULED.value:
                            if not is_locked(match.match_date, tz_name=settings.timezone):
                                await run_phase2(db, match)

                        elif match.status == MatchStatus.DATA_READY.value:
                            if not is_locked(match.match_date, tz_name=settings.timezone):
                                await run_phase3(db, match, "scheduled")

                        elif match.status == MatchStatus.PREDICTED.value:
                            if is_locked(match.match_date, tz_name=settings.timezone):
                                match.status = MatchStatus.LOCKED.value
                                await db.commit()
                            else:
                                if await check_volatility(db, match):
                                    await run_phase3(db, match, "odds_jump")

                        elif match.status == MatchStatus.LOCKED.value:
                            kickoff_naive = match.kickoff_time.replace(tzinfo=None) if match.kickoff_time.tzinfo else match.kickoff_time
                            if match.kickoff_time and now > kickoff_naive + timedelta(hours=3):
                                match.status = MatchStatus.FINISHED.value
                                await db.commit()

                        elif match.status == MatchStatus.FINISHED.value:
                            await run_phase4(db, match)

                    except Exception as e:
                        logger.error(f"Pipeline error for {match.match_id}: {e}")
                        match.status = MatchStatus.ERROR.value
                        match.error_count += 1
                        await db.commit()

        except Exception as e:
            logger.error(f"Pipeline loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting Football Prediction System V4.0 (Lite Mode)...")
    await init_db()
    logger.info("Database initialized (SQLite)")

    # Start background pipeline
    pipeline_task = asyncio.create_task(_pipeline_loop())
    logger.info("Background pipeline started")

    yield

    pipeline_task.cancel()
    logger.info("Shutting down...")


app = FastAPI(
    title="Football Prediction System",
    description="全自动AI足球赛事分析与预测系统 V4.0",
    version="4.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(matches_router)
app.include_router(monitor_router)
app.include_router(admin_router)

# Static files (for frontend dashboard)
app.mount("/static", StaticFiles(directory="app/static", html=True), name="static")


@app.get("/", tags=["root"])
async def root():
    """Root endpoint: redirect to dashboard."""
    return {
        "system": "Football Prediction System V4.0",
        "mode": "lite (SQLite + background tasks)",
        "docs": "/docs",
        "dashboard": "/static/index.html",
        "api": "/api",
    }


@app.get("/api", tags=["root"])
async def api_root():
    """API overview."""
    return {
        "endpoints": {
            "matches": "/api/matches",
            "monitor": "/api/monitor",
            "admin": "/api/admin",
        }
    }
