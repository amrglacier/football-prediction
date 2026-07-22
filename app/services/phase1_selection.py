"""Phase 1: Match Selection (赛选层)

Fetches fixtures from football data API, filters by league whitelist
and odds range, stores initial odds and outputs MatchList.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import DEFAULT_LEAGUES, DEFAULT_ODDS_RANGE
from app.core.state_machine import get_cutoff_time
from app.models.models import Match, OddsInitial
from app.services.football_api import football_client

logger = logging.getLogger(__name__)


async def run_phase1(
    db: AsyncSession,
    target_date: Optional[date] = None,
    leagues: Optional[list[str]] = None,
    odds_range: Optional[tuple[float, float]] = None,
) -> list[Match]:
    """
    Execute Phase 1: Match Selection.

    1. Fetch fixtures from API for the target date
    2. Filter by league whitelist
    3. Filter by odds range (if odds available)
    4. Store initial odds
    5. Calculate cutoff times
    6. Return list of Match objects
    """
    if target_date is None:
        target_date = date.today() + timedelta(days=1)  # Default: tomorrow

    if leagues is None:
        leagues = DEFAULT_LEAGUES

    if odds_range is None:
        odds_range = DEFAULT_ODDS_RANGE

    logger.info(f"Phase 1: Fetching fixtures for {target_date}, leagues={leagues}")

    # Fetch raw fixtures from API
    raw_fixtures = await football_client.get_fixtures(target_date, leagues)

    if not raw_fixtures:
        logger.warning("Phase 1: No fixtures returned from API")
        # If API unavailable, return empty list (graceful degradation)
        return []

    matches_to_create = []

    for raw in raw_fixtures:
        # Normalize fixture to internal format
        normalized = football_client.normalize_fixture(raw, leagues)
        if normalized is None:
            continue  # League not in whitelist

        # Fetch initial odds (free tier may not provide odds)
        fixture_id = normalized.get("api_fixture_id", "")
        odds = await football_client.get_odds(fixture_id)

        # Filter by odds range if odds are available
        if odds:
            min_odds, max_odds = odds_range
            all_in_range = all(min_odds <= v <= max_odds for v in [odds["h"], odds["d"], odds["a"]])
            if not all_in_range:
                logger.debug(f"Phase 1: Skipping {normalized['home']} vs {normalized['away']} - odds out of range")
                continue

        # Calculate cutoff time
        match_date = date.fromisoformat(normalized["match_date"])
        cutoff = get_cutoff_time(match_date, settings.timezone)

        # Parse kickoff time
        kickoff_dt = datetime.fromisoformat(normalized["kickoff"])

        # Create Match object
        match = Match(
            match_id=normalized["match_id"],
            league=normalized["league"],
            home=normalized["home"],
            away=normalized["away"],
            kickoff_time=kickoff_dt,
            match_date=match_date,
            cutoff_time=cutoff,
            status="SCHEDULED",
            api_fixture_id=normalized["api_fixture_id"],
        )
        matches_to_create.append(match)

        # Store initial odds if available
        if odds:
            odds_record = OddsInitial(
                match_id=normalized["match_id"],
                h=odds["h"],
                d=odds["d"],
                a=odds["a"],
            )
            db.add(odds_record)

    # Save matches to database
    for match in matches_to_create:
        # Check if match already exists
        existing = await db.execute(
            select(Match).where(Match.match_id == match.match_id)
        )
        if not existing.scalar_one_or_none():
            db.add(match)

    await db.commit()

    logger.info(f"Phase 1: Selected {len(matches_to_create)} matches")
    return matches_to_create
