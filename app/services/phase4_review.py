"""Phase 4: Review & Iteration (复盘层)

Fetches match results, compares against V_latest, performs error attribution
and updates factor weights using the adaptive learning formula.
"""

import logging
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import (
    MatchStatus, ERROR_TAXONOMY, FACTOR_DEFINITIONS,
)
from app.core.state_machine import is_valid_transition
from app.core.weights import iterate_weight, normalise_weights, get_league_sensitivity
from app.models.models import (
    Match, Prediction, ReviewReport, FactorWeight, ErrorLog,
    PredictionVersion,
)
from app.services.football_api import football_client
from app.services.phase2_data import _parse_json_response
from app.providers.registry import call_with_fallback

logger = logging.getLogger(__name__)


async def run_phase4(db: AsyncSession, match: Match) -> ReviewReport:
    """
    Execute Phase 4: Review & Iteration.

    1. Fetch actual match result
    2. Compare against V_latest prediction
    3. Perform error attribution (E001-E008)
    4. Update factor weights using adaptive formula
    5. Store ReviewReport
    """
    logger.info(f"Phase 4: Starting review for {match.match_id}")

    # Fetch actual result
    if not match.api_fixture_id:
        logger.warning(f"Phase 4: No API fixture ID for {match.match_id}")
        # Use stored result if available
        if match.actual_result and match.actual_score:
            actual = {"result": match.actual_result, "score": match.actual_score}
        else:
            raise ValueError("No actual result available")
    else:
        actual = await football_client.get_match_result(int(match.api_fixture_id))
        if not actual:
            # Try using stored result
            if match.actual_result:
                actual = {"result": match.actual_result, "score": match.actual_score or "0-0"}
            else:
                logger.warning(f"Phase 4: Could not fetch result for {match.match_id}")
                return None

    # Load V_latest prediction
    pred_result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match.match_id,
            Prediction.version == PredictionVersion.V_LATEST.value
        )
    )
    v_latest = pred_result.scalar_one_or_none()

    # Load V0 prediction
    v0_result = await db.execute(
        select(Prediction).where(
            Prediction.match_id == match.match_id,
            Prediction.version == PredictionVersion.V0.value
        )
    )
    v0 = v0_result.scalar_one_or_none()

    # Calculate hit status
    actual_result = actual["result"]
    actual_score = actual["score"]

    hit_result = False
    hit_score = False
    hit_goals = False
    hit_half_full = False

    if v_latest:
        hit_result = v_latest.final_result == actual_result

        # Check score hit
        if v_latest.final_score:
            hit_score = actual_score in v_latest.final_score

        # Check goals hit
        actual_goals = int(actual_score.split("-")[0]) + int(actual_score.split("-")[1])
        if v_latest.final_goals is not None:
            hit_goals = v_latest.final_goals == actual_goals

    # Determine prediction shift
    prediction_shift = "none"
    if v0 and v_latest and v0.final_result != v_latest.final_result:
        prediction_shift = f"{v0.final_result}->{v_latest.final_result}"

    # Error attribution
    error_analysis = await _attribute_errors(
        db, match, v_latest, actual_result, actual_score
    )

    # Update factor weights
    weight_adjustment = await _update_weights(db, match, error_analysis)

    # Create review report
    report = ReviewReport(
        match_id=match.match_id,
        actual_result=actual_result,
        actual_score=actual_score,
        hit_result=hit_result,
        hit_score=hit_score,
        hit_goals=hit_goals,
        hit_half_full=hit_half_full,
        v0_prediction=v0.final_result if v0 else None,
        v_latest_prediction=v_latest.final_result if v_latest else None,
        prediction_shift=prediction_shift,
        error_analysis=error_analysis,
        weight_adjustment=weight_adjustment,
    )

    db.add(report)

    # Update match status
    match.status = MatchStatus.REVIEWED.value
    match.actual_result = actual_result
    match.actual_score = actual_score
    await db.commit()

    logger.info(f"Phase 4: Completed review for {match.match_id}. Hit: {hit_result}")
    return report


async def _attribute_errors(
    db: AsyncSession,
    match: Match,
    prediction: Optional[Prediction],
    actual_result: str,
    actual_score: str,
) -> list[dict]:
    """
    Attribute prediction errors to specific factors.
    Uses rule-based heuristics + optional AI analysis.
    """
    errors = []

    if not prediction:
        return errors

    # If prediction was correct, no errors to attribute
    if prediction.final_result == actual_result:
        return errors

    # Rule-based error attribution
    committee = prediction.committee_details or []

    for member in committee:
        factor_id = member.get("factor_id", "")
        vote = member.get("vote", "")
        confidence = member.get("confidence", 0.5)

        # If this factor voted for the wrong result with high confidence
        if vote != actual_result and confidence > 0.5:
            error_code = _map_factor_to_error(factor_id)
            error_entry = ERROR_TAXONOMY.get(error_code, {})

            errors.append({
                "factor_id": factor_id,
                "is_culprit": True,
                "error_code": error_code,
                "error_desc": error_entry.get("desc", f"因子 {factor_id} 预测错误"),
                "vote": vote,
                "actual": actual_result,
                "confidence": confidence,
            })

            # Log error
            log_entry = ErrorLog(
                match_id=match.match_id,
                error_code=error_code,
                factor_id=factor_id,
                description=f"{match.home} vs {match.away}: {error_entry.get('desc', '')}. "
                           f"Vote={vote}, Actual={actual_result}",
                stage="phase4",
            )
            db.add(log_entry)

    # If no specific factor errors found but prediction was wrong,
    # attribute to the top-weighted factor that voted for the predicted result
    if not errors and prediction.final_result != actual_result:
        for member in committee:
            if member.get("vote") == prediction.final_result:
                factor_id = member.get("factor_id", "")
                error_code = _map_factor_to_error(factor_id)
                error_entry = ERROR_TAXONOMY.get(error_code, {})

                errors.append({
                    "factor_id": factor_id,
                    "is_culprit": True,
                    "error_code": error_code,
                    "error_desc": error_entry.get("desc", "预测错误"),
                    "vote": member.get("vote"),
                    "actual": actual_result,
                    "confidence": member.get("confidence", 0.5),
                })
                break

    return errors


def _map_factor_to_error(factor_id: str) -> str:
    """Map a factor ID to its corresponding error code."""
    mapping = {
        "F1": "E001",
        "F2": "E002",
        "F3": "E003",
        "F4": "E004",
        "F5": "E005",
        "F6": "E006",
        "F7": "E007",
        "F8": "E008",
    }
    return mapping.get(factor_id, "E001")


async def _update_weights(
    db: AsyncSession,
    match: Match,
    error_analysis: list[dict],
) -> dict:
    """
    Update factor weights based on error analysis.
    Uses the formula: W_new = W_old * (1 - eta * Delta * I_league)
    """
    if not error_analysis:
        return {"league": match.league, "before": {}, "after": {}, "reason": "No errors"}

    league = match.league
    before_weights = {}
    after_weights = {}

    # Load current weights for this league
    for error in error_analysis:
        factor_id = error["factor_id"]

        # Get current weight from DB or compute default
        weight_result = await db.execute(
            select(FactorWeight).where(
                FactorWeight.factor_id == factor_id,
                FactorWeight.league == league
            )
        )
        weight_record = weight_result.scalar_one_or_none()

        if weight_record:
            old_weight = weight_record.weight
        else:
            # Use default from BASE_WEIGHTS
            from app.core.constants import BASE_WEIGHTS
            old_weight = BASE_WEIGHTS.get(factor_id, 0.10)

        before_weights[factor_id] = old_weight

        # Apply iteration formula
        new_weight = iterate_weight(factor_id, league, old_weight, is_error=True)
        after_weights[factor_id] = new_weight

        # Update or create weight record
        if weight_record:
            weight_record.weight = new_weight
        else:
            new_record = FactorWeight(
                factor_id=factor_id,
                league=league,
                weight=new_weight,
            )
            db.add(new_record)

    # Log the adjustment
    error_codes = [e["error_code"] for e in error_analysis]
    reason = f"{' & '.join(error_codes)} in {league}"

    logger.info(f"Phase 4: Weight adjustment for {league}: {before_weights} -> {after_weights}")

    return {
        "league": league,
        "before": before_weights,
        "after": after_weights,
        "reason": reason,
    }
