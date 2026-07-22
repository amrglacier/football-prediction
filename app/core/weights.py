"""Dynamic weight calculation and iteration engine."""

from typing import Dict

from app.core.constants import (
    BASE_WEIGHTS,
    LEAGUE_WEIGHT_RULES,
    LEAGUE_SENSITIVITY,
    FACTOR_DEFINITIONS,
    FOCUS_MATCH_KEYWORDS,
)
from app.config import settings


def get_dynamic_weights(league: str, is_focus_match: bool = False) -> Dict[str, float]:
    """
    Calculate dynamic weights for a given league and match type.

    Starts from BASE_WEIGHTS, applies league-specific adjustments,
    then normalises so the total sums to 1.0.
    """
    weights = dict(BASE_WEIGHTS)

    # League-specific adjustments
    league_rule = LEAGUE_WEIGHT_RULES.get(league, {})
    for factor_id, delta in league_rule.items():
        if factor_id in weights:
            weights[factor_id] += delta

    # Focus match / derby: ColdHunter (F7) +5%
    if is_focus_match:
        weights["F7"] = weights.get("F7", 0.10) + 0.05
    else:
        # Ordinary match: OddsPsychologist (F1) +5%
        weights["F1"] = weights.get("F1", 0.20) + 0.05

    # Normalise to sum 1.0
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 4) for k, v in weights.items()}

    return weights


def detect_focus_match(home: str, away: str, league: str, context: str = "") -> bool:
    """Detect whether a match is a focus / derby match."""
    combined = f"{home} {away} {league} {context}"
    for keyword in FOCUS_MATCH_KEYWORDS:
        if keyword in combined:
            return True
    return False


def iterate_weight(
    factor_id: str,
    league: str,
    old_weight: float,
    is_error: bool = True,
) -> float:
    """
    Apply the adaptive weight iteration formula:
        W_new = W_old * (1 - eta * Delta * I_league)

    - eta: learning rate
    - Delta: 1 if error, 0 if correct
    - I_league: league sensitivity coefficient
    """
    if not is_error:
        return old_weight  # No change for correct predictions

    eta = settings.learning_rate
    delta = 1  # penalty

    league_sensitivity = LEAGUE_SENSITIVITY.get(league, 1.0)

    new_weight = old_weight * (1 - eta * delta * league_sensitivity)

    # Clamp to minimum 0.01 to avoid zeroing out completely
    new_weight = max(new_weight, 0.01)

    return round(new_weight, 4)


def normalise_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalise a weight dict so values sum to 1.0."""
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {k: round(v / total, 4) for k, v in weights.items()}


def get_league_sensitivity(league: str) -> float:
    """Get the league sensitivity coefficient for weight penalties."""
    return LEAGUE_SENSITIVITY.get(league, 1.0)
