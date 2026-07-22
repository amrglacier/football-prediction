"""Celery application and task definitions.

Handles the automated pipeline orchestration:
  - Daily fixture fetching (Phase 1)
  - Data acquisition (Phase 2)
  - Scheduled predictions (Phase 3)
  - Post-match review (Phase 4)
  - Lock/cutoff enforcement
"""

import logging
from datetime import date, datetime, timedelta

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import MatchStatus, TriggerReason
from app.core.state_machine import is_locked
from app.core.database import async_session_factory
from app.models.models import Match, Prediction, PredictionVersion
from app.services.phase1_selection import run_phase1
from app.services.phase2_data import run_phase2
from app.services.phase3_predict import run_phase3, check_volatility
from app.services.phase4_review import run_phase4

logger = logging.getLogger(__name__)

celery_app = Celery(
    "football_prediction",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
)


# ============================================================
# Helper: run async function in sync Celery context
# ============================================================

async def _run_async(coro_func, *args, **kwargs):
    """Run an async function within an async DB session."""
    async with async_session_factory() as db:
        return await coro_func(db, *args, **kwargs)


def run_async(coro_func, *args, **kwargs):
    """Sync wrapper for async functions."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_async(coro_func, *args, **kwargs))
    finally:
        loop.close()


# ============================================================
# Celery Tasks
# ============================================================

@celery_app.task(name="tasks.fetch_fixtures")
def fetch_fixtures_task(target_date_str: str = None):
    """Phase 1: Fetch and store fixtures for a given date."""
    target_date = date.fromisoformat(target_date_str) if target_date_str else date.today() + timedelta(days=1)
    logger.info(f"Celery: Fetching fixtures for {target_date}")
    result = run_async(run_phase1, target_date=target_date)
    return {"status": "ok", "date": str(target_date), "matches": len(result)}


@celery_app.task(name="tasks.acquire_data")
def acquire_data_task(match_id: str):
    """Phase 2: Acquire data for a specific match."""
    async def _run():
        async with async_session_factory() as db:
            result = await db.execute(select(Match).where(Match.match_id == match_id))
            match = result.scalar_one_or_none()
            if not match:
                raise ValueError(f"Match {match_id} not found")
            return await run_phase2(db, match)

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        briefing = loop.run_until_complete(_run())
        return {"status": "ok", "match_id": match_id}
    finally:
        loop.close()


@celery_app.task(name="tasks.generate_prediction")
def generate_prediction_task(match_id: str, trigger_reason: str = "scheduled"):
    """Phase 3: Generate prediction for a specific match."""
    async def _run():
        async with async_session_factory() as db:
            result = await db.execute(select(Match).where(Match.match_id == match_id))
            match = result.scalar_one_or_none()
            if not match:
                raise ValueError(f"Match {match_id} not found")
            return await run_phase3(db, match, trigger_reason)

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        prediction = loop.run_until_complete(_run())
        return {"status": "ok", "match_id": match_id, "prediction_id": prediction.prediction_id if prediction else None}
    finally:
        loop.close()


@celery_app.task(name="tasks.review_match")
def review_match_task(match_id: str):
    """Phase 4: Review a completed match."""
    async def _run():
        async with async_session_factory() as db:
            result = await db.execute(select(Match).where(Match.match_id == match_id))
            match = result.scalar_one_or_none()
            if not match:
                raise ValueError(f"Match {match_id} not found")
            return await run_phase4(db, match)

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        report = loop.run_until_complete(_run())
        return {"status": "ok", "match_id": match_id, "hit": report.hit_result if report else None}
    finally:
        loop.close()


# ============================================================
# Scheduled pipeline tasks (beat schedule)
# ============================================================

@celery_app.task(name="tasks.run_pipeline")
def run_pipeline_task():
    """
    Main pipeline loop: runs every minute.
    Checks all matches and advances their state according to the state machine.
    """
    async def _run():
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
                    await _process_match(db, match, now)
                except Exception as e:
                    logger.error(f"Pipeline error for {match.match_id}: {e}")
                    match.status = MatchStatus.ERROR.value
                    match.error_count += 1
                    await db.commit()

    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_run())


async def _process_match(db: AsyncSession, match: Match, now: datetime):
    """Process a single match in the pipeline based on its current state."""
    tz_name = settings.timezone

    if match.status == MatchStatus.SCHEDULED.value:
        # Start Phase 2 if not locked
        if not is_locked(match.match_date, tz_name=tz_name):
            await run_phase2(db, match)

    elif match.status == MatchStatus.DATA_READY.value:
        # Start Phase 3 (initial prediction) if not locked
        if not is_locked(match.match_date, tz_name=tz_name):
            await run_phase3(db, match, TriggerReason.SCHEDULED.value)

    elif match.status == MatchStatus.PREDICTED.value:
        # Check if should lock
        if is_locked(match.match_date, tz_name=tz_name):
            match.status = MatchStatus.LOCKED.value
            await db.commit()
        else:
            # Check volatility for strong change point
            if await check_volatility(db, match):
                await run_phase3(db, match, TriggerReason.ODDS_JUMP.value)
            elif await _should_run_scheduled_prediction(db, match):
                await run_phase3(db, match, TriggerReason.SCHEDULED.value)

    elif match.status == MatchStatus.LOCKED.value:
        # Check if match has finished
        if match.kickoff_time and now > match.kickoff_time + timedelta(hours=3):
            match.status = MatchStatus.FINISHED.value
            await db.commit()

    elif match.status == MatchStatus.FINISHED.value:
        # Run Phase 4 review
        await run_phase4(db, match)


async def _should_run_scheduled_prediction(db: AsyncSession, match: Match) -> bool:
    """Check if a scheduled prediction should run (delta_t check)."""
    result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match.match_id,
        ).order_by(Prediction.snapshot_time.desc()).limit(1)
    )
    latest = result.scalar_one_or_none()
    if not latest:
        return True
    delta = datetime.utcnow() - latest.snapshot_time
    return delta >= timedelta(minutes=settings.delta_t)


# ============================================================
# Beat schedule (cron-like)
# ============================================================

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # Run main pipeline every minute
    "pipeline-loop": {
        "task": "tasks.run_pipeline",
        "schedule": 60.0,
    },
    # Fetch fixtures daily at 08:00
    "daily-fetch": {
        "task": "tasks.fetch_fixtures",
        "schedule": crontab(hour=8, minute=0),
    },
}
