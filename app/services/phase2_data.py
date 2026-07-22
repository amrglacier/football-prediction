"""Phase 2: Data Acquisition (数据层)

Quantifier collects data, Verifier cross-checks, then anchor odds are captured.
Outputs VerifiedBriefing.
"""

import logging
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import MatchStatus
from app.core.state_machine import is_valid_transition
from app.models.models import Match, VerifiedBriefing, OddsInitial
from app.providers.registry import call_with_fallback
from app.prompts.templates import quantifier_prompts, verifier_prompts
from app.services.football_api import football_client

logger = logging.getLogger(__name__)


async def run_phase2(db: AsyncSession, match: Match) -> VerifiedBriefing:
    """
    Execute Phase 2: Data Acquisition for a single match.

    1. Update match status to DATA_FETCHING
    2. Quantifier (Qwen) collects fundamental data
    3. Verifier (ERNIE/Hunyuan) cross-checks data
    4. Capture anchor odds
    5. Store VerifiedBriefing
    6. Update match status to DATA_READY
    """
    logger.info(f"Phase 2: Starting data acquisition for {match.match_id}")

    # State transition: SCHEDULED -> DATA_FETCHING
    if not is_valid_transition(MatchStatus(match.status), MatchStatus.DATA_FETCHING):
        logger.warning(f"Phase 2: Invalid state transition from {match.status}")
        # Allow retry from ERROR state
        if match.status != MatchStatus.ERROR.value:
            raise ValueError(f"Cannot start Phase 2 from state {match.status}")

    match.status = MatchStatus.DATA_FETCHING.value
    await db.commit()

    try:
        # Prepare match info for AI
        match_info = {
            "match_id": match.match_id,
            "league": match.league,
            "home": match.home,
            "away": match.away,
            "kickoff": match.kickoff_time.isoformat(),
            "match_date": match.match_date.isoformat(),
        }

        # Step 1: Quantifier collects data
        logger.info(f"Phase 2: Quantifier collecting data for {match.match_id}")
        quant_sys, quant_user = quantifier_prompts(match_info)
        quant_result = await call_with_fallback(
            "F2",  # Qwen is the quantifier
            quant_sys, quant_user,
            temperature=0.1,  # Low temperature for factual data
            max_tokens=3000,
        )

        raw_briefing = _parse_json_response(quant_result)

        # Step 2: Verifier cross-checks data
        logger.info(f"Phase 2: Verifier cross-checking data for {match.match_id}")
        verify_sys, verify_user = verifier_prompts(match_info, raw_briefing)
        verify_result = await call_with_fallback(
            "F7",  # ERNIE as verifier (different model for independence)
            verify_sys, verify_user,
            temperature=0.1,
            max_tokens=3000,
        )

        verified_briefing = _parse_json_response(verify_result)

        # Ensure required fields exist
        if "content" not in verified_briefing:
            verified_briefing["content"] = raw_briefing.get("content", {})
        if "data_confidence" not in verified_briefing:
            verified_briefing["data_confidence"] = "medium"

        # Step 3: Capture anchor odds
        anchor_odds = await _capture_anchor_odds(match)

        # Step 4: Store VerifiedBriefing
        briefing = VerifiedBriefing(
            match_id=match.match_id,
            data_confidence=verified_briefing.get("data_confidence", "medium"),
            content_json=verified_briefing.get("content", verified_briefing),
            odds_anchor=anchor_odds,
        )

        # Delete old briefing if exists
        old_briefing = await db.execute(
            select(VerifiedBriefing).where(VerifiedBriefing.match_id == match.match_id)
        )
        for old in old_briefing.scalars().all():
            await db.delete(old)

        db.add(briefing)

        # Step 5: Update match status
        match.status = MatchStatus.DATA_READY.value
        await db.commit()

        logger.info(f"Phase 2: Completed for {match.match_id}")
        return briefing

    except Exception as e:
        logger.error(f"Phase 2: Failed for {match.match_id}: {e}")
        match.status = MatchStatus.ERROR.value
        match.error_count += 1
        await db.commit()
        raise


async def _capture_anchor_odds(match: Match) -> dict:
    """Capture current odds as anchor odds."""
    # Try to fetch live odds from API
    if match.api_fixture_id:
        fixture_id = int(match.api_fixture_id)
        live_odds = await football_client.get_odds(fixture_id)
        if live_odds:
            return {
                "snapshot_time": datetime.utcnow().isoformat(),
                "h": live_odds["h"],
                "d": live_odds["d"],
                "a": live_odds["a"],
            }

    # Fallback: use initial odds from database
    # This is handled at the service layer since we need db access
    return {
        "snapshot_time": datetime.utcnow().isoformat(),
        "h": 0.0, "d": 0.0, "a": 0.0,  # Placeholder, will be filled from DB
        "note": "Anchor odds pending - using placeholder"
    }


def _parse_json_response(text: str) -> dict:
    """Parse a JSON response from AI, handling markdown code fences."""
    # Remove markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json ... ```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse JSON response, returning empty dict")
        return {}
