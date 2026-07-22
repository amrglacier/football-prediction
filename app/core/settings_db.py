"""Application settings stored in SQLite (configurable at runtime)."""

import json
import logging
from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ModelParam

logger = logging.getLogger(__name__)

# Default leagues and their active status
DEFAULT_LEAGUES_CONFIG = {
    "英超": True, "西甲": True, "意甲": True, "德甲": True, "法甲": True,
    "瑞超": True, "芬超": True, "挪超": True,
}


async def get_league_whitelist(db: AsyncSession) -> List[str]:
    """Return list of active leagues from DB, fallback to defaults."""
    result = await db.execute(
        select(ModelParam).where(ModelParam.param_name == "league_whitelist")
    )
    param = result.scalar_one_or_none()

    if param:
        try:
            config = json.loads(param.value)
            active = [league for league, enabled in config.items() if enabled]
            return active if active else list(DEFAULT_LEAGUES_CONFIG.keys())
        except Exception:
            pass

    return list(DEFAULT_LEAGUES_CONFIG.keys())


async def get_league_config(db: AsyncSession) -> dict:
    """Return full league config dict."""
    result = await db.execute(
        select(ModelParam).where(ModelParam.param_name == "league_whitelist")
    )
    param = result.scalar_one_or_none()

    if param:
        try:
            return json.loads(param.value)
        except Exception:
            pass

    return dict(DEFAULT_LEAGUES_CONFIG)


async def set_league_config(db: AsyncSession, config: dict) -> None:
    """Update league whitelist configuration."""
    result = await db.execute(
        select(ModelParam).where(ModelParam.param_name == "league_whitelist")
    )
    param = result.scalar_one_or_none()

    if param:
        param.value = json.dumps(config)
    else:
        param = ModelParam(
            param_name="league_whitelist",
            value=json.dumps(config),
            description="League whitelist config",
        )
        db.add(param)

    await db.commit()
    logger.info(f"Updated league config: {config}")
