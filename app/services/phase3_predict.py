"""Phase 3: Multi-Factor Committee (预测层)

8 factors vote in parallel, coordinator aggregates with dynamic weights,
manages prediction versions (V0/V_latest/V_hist).
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import (
    MatchStatus, FACTOR_DEFINITIONS, TriggerReason, PredictionVersion,
    MAX_HISTORY,
)
from app.core.state_machine import is_valid_transition, can_predict, is_locked
from app.core.weights import get_dynamic_weights, detect_focus_match
from app.models.models import (
    Match, VerifiedBriefing, Prediction, PredictionHistory,
    OddsInitial, FactorWeight,
)
from app.providers.registry import call_with_fallback
from app.prompts.templates import get_factor_prompts, coordinator_prompts, FACTOR_VOTE_FORMAT
from app.services.phase2_data import _parse_json_response

logger = logging.getLogger(__name__)


async def run_phase3(
    db: AsyncSession,
    match: Match,
    trigger_reason: str = TriggerReason.SCHEDULED.value,
) -> Prediction:
    """
    Execute Phase 3: Multi-Factor Committee prediction.

    1. Check cutoff time (no predictions after cutoff)
    2. Update match status to PREDICTING
    3. Load VerifiedBriefing and odds data
    4. Calculate dynamic weights
    5. 8 factors vote in parallel
    6. Coordinator aggregates votes
    7. Store prediction (V0 / V_latest / V_hist)
    8. Update match status to PREDICTED
    """
    # Check cutoff
    if is_locked(match.match_date, tz_name=settings.timezone):
        logger.info(f"Phase 3: Match {match.match_id} is locked, skipping prediction")
        # Return existing V_latest if available
        existing = await db.execute(
            select(Prediction).where(
                Prediction.match_id == match.match_id,
                Prediction.version == PredictionVersion.V_LATEST.value
            )
        )
        return existing.scalar_one_or_none()

    # Check delta_t for scheduled triggers
    if trigger_reason == TriggerReason.SCHEDULED.value:
        if not await _should_run_scheduled(db, match):
            logger.info(f"Phase 3: Skipping {match.match_id} - within delta_t window")
            existing = await db.execute(
                select(Prediction).where(
                    Prediction.match_id == match.match_id,
                    Prediction.version == PredictionVersion.V_LATEST.value
                )
            )
            return existing.scalar_one_or_none()

    logger.info(f"Phase 3: Starting prediction for {match.match_id}, trigger={trigger_reason}")

    # State transition
    match.status = MatchStatus.PREDICTING.value
    await db.commit()

    try:
        # Load briefing
        briefing_result = await db.execute(
            select(VerifiedBriefing).where(VerifiedBriefing.match_id == match.match_id)
        )
        briefing = briefing_result.scalar_one_or_none()
        if not briefing:
            raise ValueError(f"No VerifiedBriefing found for {match.match_id}")

        # Load odds data
        odds_data = await _load_odds_data(db, match, briefing)

        # Calculate dynamic weights
        is_focus = match.is_focus_match or detect_focus_match(match.home, match.away, match.league)
        weights = get_dynamic_weights(match.league, is_focus)

        # Prepare briefing content for factors
        briefing_content = briefing.content_json if briefing.content_json else {}
        briefing_content["match_info"] = {
            "match_id": match.match_id,
            "league": match.league,
            "home": match.home,
            "away": match.away,
            "kickoff": match.kickoff_time.isoformat(),
        }

        # Step 1: 8 factors vote in parallel
        factor_votes = await _collect_factor_votes(briefing_content, odds_data)

        # Step 2: Coordinator aggregates
        current_time = datetime.utcnow().isoformat()
        match_info = {
            "match_id": match.match_id,
            "league": match.league,
            "home": match.home,
            "away": match.away,
        }

        coord_sys, coord_user = coordinator_prompts(
            briefing_content, factor_votes, weights, current_time, match_info
        )

        coord_result = await call_with_fallback(
            "F1",  # Use F1's provider chain for coordinator (Claude/DeepSeek)
            coord_sys, coord_user,
            temperature=0.2,
            max_tokens=3000,
        )

        final_report = _parse_json_response(coord_result)

        # If AI failed to produce valid report, compute locally
        if not final_report.get("final_prediction"):
            final_report = _compute_locally(factor_votes, weights)

        # Step 3: Store prediction
        prediction = await _store_prediction(
            db, match, final_report, factor_votes, weights,
            odds_data, trigger_reason
        )

        # Update match status
        match.status = MatchStatus.PREDICTED.value
        await db.commit()

        logger.info(f"Phase 3: Completed prediction for {match.match_id}")
        return prediction

    except Exception as e:
        logger.error(f"Phase 3: Failed for {match.match_id}: {e}")
        match.status = MatchStatus.ERROR.value
        match.error_count += 1
        await db.commit()
        raise


async def _collect_factor_votes(briefing: dict, odds_data: dict) -> list[dict]:
    """Collect votes from all 8 factors in parallel."""
    tasks = []
    factor_ids = list(FACTOR_DEFINITIONS.keys())

    for factor_id in factor_ids:
        task = _get_single_factor_vote(factor_id, briefing, odds_data)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    votes = []
    for i, result in enumerate(results):
        factor_id = factor_ids[i]
        factor_def = FACTOR_DEFINITIONS[factor_id]

        if isinstance(result, Exception):
            logger.warning(f"Factor {factor_id} failed: {result}")
            # Create a skipped factor vote
            votes.append({
                "factor_id": factor_id,
                "factor_name": factor_def["name"],
                "vote": "平局",  # Neutral default
                "confidence": 0.0,
                "reasoning": f"[FACTOR_SKIPPED] {str(result)[:100]}",
                "weight_used": 0.0,
                "derived_metrics": {
                    "predicted_scores": [],
                    "predicted_goals": 0,
                    "predicted_half_full": []
                }
            })
        else:
            vote = result
            vote["factor_id"] = factor_id
            vote["factor_name"] = factor_def["name"]
            votes.append(vote)

    return votes


async def _get_single_factor_vote(factor_id: str, briefing: dict, odds_data: dict) -> dict:
    """Get a single factor's vote via AI."""
    factor_def = FACTOR_DEFINITIONS[factor_id]

    system_prompt, user_prompt = get_factor_prompts(factor_id, briefing, odds_data)

    # Append format reminder
    system_prompt += FACTOR_VOTE_FORMAT % (factor_id, factor_def["name"])

    result = await call_with_fallback(
        factor_id, system_prompt, user_prompt,
        temperature=0.3,
        max_tokens=1500,
    )

    vote = _parse_json_response(result)

    # Validate required fields
    if "vote" not in vote or vote["vote"] not in ["主胜", "平局", "客胜"]:
        vote["vote"] = "平局"  # Default to neutral
    if "confidence" not in vote or not isinstance(vote["confidence"], (int, float)):
        vote["confidence"] = 0.5
    if "reasoning" not in vote:
        vote["reasoning"] = ""
    if "derived_metrics" not in vote:
        vote["derived_metrics"] = {
            "predicted_scores": [],
            "predicted_goals": 0,
            "predicted_half_full": []
        }

    return vote


def _compute_locally(factor_votes: list[dict], weights: dict[str, float]) -> dict:
    """Compute prediction locally as fallback when AI coordinator fails."""
    # Weighted voting
    scores = {"主胜": 0.0, "平局": 0.0, "客胜": 0.0}

    for vote in factor_votes:
        factor_id = vote.get("factor_id", "")
        weight = weights.get(factor_id, 0.0)
        confidence = vote.get("confidence", 0.5)
        result = vote.get("vote", "平局")
        scores[result] += weight * confidence

    final_result = max(scores, key=scores.get)

    # Collect predicted scores
    all_scores = []
    all_goals = []
    all_half_full = []
    for vote in factor_votes:
        dm = vote.get("derived_metrics", {})
        all_scores.extend(dm.get("predicted_scores", []))
        all_goals.append(dm.get("predicted_goals", 0))
        all_half_full.extend(dm.get("predicted_half_full", []))

    # Pick most common score
    from collections import Counter
    score_counter = Counter(all_scores)
    final_scores = [s for s, _ in score_counter.most_common(2)] if all_scores else ["1-1"]
    final_goals = round(sum(all_goals) / len(all_goals)) if all_goals else 2
    hf_counter = Counter(all_half_full)
    final_hf = [h for h, _ in hf_counter.most_common(2)] if all_half_full else ["平平"]

    # Build reasoning
    reasoning_parts = []
    for vote in factor_votes:
        fid = vote.get("factor_id", "")
        reasoning = vote.get("reasoning", "")
        if reasoning:
            reasoning_parts.append(f"{fid}: {reasoning[:50]}")

    # Check for risk warning
    has_risk = False
    risk_text = ""
    for vote in factor_votes:
        if vote.get("factor_id") == "F7" and vote.get("confidence", 0) > 0.7:
            has_risk = True
            risk_text = "F7(冷门猎手)发出高风险警示"
            break

    return {
        "final_prediction": {
            "result": final_result,
            "score": final_scores,
            "goals": final_goals,
            "half_full": final_hf,
            "reasoning_summary": " | ".join(reasoning_parts[:5]),
        },
        "has_risk_warning": has_risk,
        "risk_warning_text": risk_text,
    }


async def _store_prediction(
    db: AsyncSession,
    match: Match,
    final_report: dict,
    factor_votes: list[dict],
    weights: dict,
    odds_data: dict,
    trigger_reason: str,
) -> Prediction:
    """Store prediction with version management logic."""
    final_pred = final_report.get("final_prediction", {})
    if not final_pred:
        final_pred = final_report  # Fallback if structure is different

    # Determine version
    existing_v0 = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match.match_id,
            Prediction.version == PredictionVersion.V0.value
        )
    )
    has_v0 = existing_v0.scalar_one_or_none() is not None

    existing_latest = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match.match_id,
            Prediction.version == PredictionVersion.V_LATEST.value
        )
    )
    current_latest = existing_latest.scalar_one_or_none()

    # If no V0 yet, this prediction becomes V0
    if not has_v0:
        version = PredictionVersion.V0.value
        snapshot_type = PredictionVersion.V0.value
    else:
        version = PredictionVersion.V_LATEST.value
        snapshot_type = PredictionVersion.V_LATEST.value

        # Move current V_latest to history
        if current_latest:
            hist = PredictionHistory(
                match_id=match.match_id,
                snapshot_time=current_latest.snapshot_time,
                trigger_reason=current_latest.trigger_reason,
                final_result=current_latest.final_result,
                final_score=current_latest.final_score,
                final_goals=current_latest.final_goals,
                committee_details=current_latest.committee_details,
                weights_used=current_latest.weights_used,
            )
            db.add(hist)

            # Trim history to MAX_HISTORY
            hist_count = await db.execute(
                select(func.count(PredictionHistory.id)).where(
                    PredictionHistory.match_id == match.match_id
                )
            )
            count = hist_count.scalar()
            if count and count > settings.max_history:
                # Delete oldest entries
                old_entries = await db.execute(
                    select(PredictionHistory)
                    .where(PredictionHistory.match_id == match.match_id)
                    .order_by(PredictionHistory.snapshot_time.asc())
                    .limit(count - settings.max_history)
                )
                for old in old_entries.scalars().all():
                    await db.delete(old)

    # Build committee_details with weights
    committee_details = []
    for vote in factor_votes:
        fid = vote.get("factor_id", "")
        detail = {
            "factor_id": fid,
            "vote": vote.get("vote", "平局"),
            "confidence": vote.get("confidence", 0.5),
            "weight_used": weights.get(fid, 0.0),
        }
        if vote.get("note"):
            detail["note"] = vote["note"]
        committee_details.append(detail)

    # Create new prediction
    prediction = Prediction(
        match_id=match.match_id,
        version=version,
        snapshot_type=snapshot_type,
        trigger_reason=trigger_reason,
        snapshot_time=datetime.utcnow(),
        final_result=final_pred.get("result", "平局"),
        final_score=final_pred.get("score", []),
        final_goals=final_pred.get("goals"),
        final_half_full=final_pred.get("half_full", []),
        reasoning_summary=final_pred.get("reasoning_summary", ""),
        committee_details=committee_details,
        weights_used=weights,
        odds_snapshot=odds_data,
        odds_snapshot_time=datetime.utcnow(),
        has_risk_warning=final_report.get("has_risk_warning", False),
        risk_warning_text=final_report.get("risk_warning_text", ""),
    )

    # If this is V_latest, delete old V_latest first
    if version == PredictionVersion.V_LATEST.value and current_latest:
        await db.delete(current_latest)

    db.add(prediction)
    await db.flush()

    return prediction


async def _load_odds_data(db: AsyncSession, match: Match, briefing: VerifiedBriefing) -> dict:
    """Load odds data (initial + anchor) for factor analysis."""
    odds_data = {"initial": None, "anchor": None}

    # Load initial odds
    initial_result = await db.execute(
        select(OddsInitial).where(OddsInitial.match_id == match.match_id)
    )
    initial = initial_result.scalar_one_or_none()
    if initial:
        odds_data["initial"] = {"h": initial.h, "d": initial.d, "a": initial.a}

    # Load anchor odds from briefing
    if briefing and briefing.odds_anchor:
        odds_data["anchor"] = briefing.odds_anchor

    return odds_data


async def _should_run_scheduled(db: AsyncSession, match: Match) -> bool:
    """Check if enough time has passed since last prediction (delta_t check)."""
    result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match.match_id,
            Prediction.version.in_([PredictionVersion.V_LATEST.value, PredictionVersion.V0.value])
        ).order_by(Prediction.snapshot_time.desc()).limit(1)
    )
    latest_pred = result.scalar_one_or_none()

    if not latest_pred:
        return True  # No prediction yet, should run

    delta = datetime.utcnow() - latest_pred.snapshot_time
    return delta >= timedelta(minutes=settings.delta_t)


async def check_volatility(db: AsyncSession, match: Match) -> bool:
    """Check if odds volatility exceeds threshold (strong change point)."""
    from app.services.football_api import football_client

    if not match.api_fixture_id:
        return False

    # Get current odds
    current_odds = await football_client.get_odds(int(match.api_fixture_id))
    if not current_odds:
        return False

    # Get anchor odds from briefing
    briefing_result = await db.execute(
        select(VerifiedBriefing).where(VerifiedBriefing.match_id == match.match_id)
    )
    briefing = briefing_result.scalar_one_or_none()
    if not briefing or not briefing.odds_anchor:
        return False

    anchor = briefing.odds_anchor
    for key in ["h", "d", "a"]:
        anchor_val = anchor.get(key, 0)
        if anchor_val > 0:
            change = abs(current_odds[key] - anchor_val) / anchor_val
            if change > settings.volatility_threshold:
                logger.info(f"Phase 3: Volatility detected for {match.match_id}: {key} changed {change:.2%}")
                return True

    return False
