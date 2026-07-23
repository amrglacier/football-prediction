"""Application settings stored in SQLite (configurable at runtime)."""

import json
import logging
from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ModelParam

logger = logging.getLogger(__name__)

# Default leagues and their active status (FULL: API-Football v3 coverage)
# Categories: 五大联赛 / 国家队赛事 / 俱乐部洲际大赛 / 各国顶级联赛 / 各国国内杯赛
DEFAULT_LEAGUES_CONFIG = {
    # ====== 五大联赛 ======
    "英超": True, "西甲": True, "意甲": True, "德甲": True, "法甲": True,
    # ====== 国家队赛事 ======
    "世界杯": True, "世界杯预选赛(欧足联)": True, "世界杯预选赛(亚足联)": True,
    "世界杯预选赛(中北美)": True, "世界杯预选赛(南美)": True, "世界杯预选赛(非洲)": True,
    "欧洲杯": True, "欧洲杯预选赛": True, "欧国联": True,
    "亚洲杯": True, "美洲杯": True, "非洲杯": True,
    "世俱杯": True, "女足世界杯": True, "女足欧洲杯": True, "奥运会足球": True,
    # ====== 俱乐部洲际大赛 ======
    "欧冠": True, "欧联": True, "欧协联": True, "欧超杯": True,
    "南美解放者杯": True, "南美杯": True,
    # ====== 各国顶级联赛 ======
    "葡超": True, "荷甲": True, "英冠": True,
    "巴西甲": True, "巴西乙": True,
    "比利时甲": True, "瑞士超": True, "奥超": True, "希腊超": True,
    "土超": True, "丹超": True, "瑞超": True, "芬超": True, "挪超": True,
    "苏超": True, "法乙": True, "德乙": True, "意乙": True, "西乙": True,
    "德丙": True, "英甲": True, "英乙": True, "英非联": True,
    "北爱超": True, "威超": True, "爱尔兰超": True,
    "冰岛超": True, "以色列超": True,
    "波兰超": True, "罗马尼亚甲": True, "克罗地亚甲": True,
    "塞尔维亚超": True, "斯洛伐克甲": True, "捷克甲": True,
    "匈牙利甲": True, "斯洛文尼亚甲": True,
    "乌克兰超": True, "俄超": True,
    "美职联": True, "墨超": True, "日职联": True, "澳超": True, "韩K联": True,
    "中超": True, "智利甲": True, "阿根廷甲": True,
    "哥伦比亚甲": True, "乌拉圭甲": True, "秘鲁甲": True,
    # ====== 各国国内杯赛 ======
    "英格兰足总杯": True, "英格兰联赛杯": True, "英格兰社区盾": True,
    "西班牙国王杯": True, "西班牙超级杯": True,
    "意大利杯": True, "意大利超级杯": True,
    "德国杯": True, "德国超级杯": True,
    "荷兰杯": True, "荷兰超级杯": True,
    "葡萄牙杯": True, "葡萄牙联赛杯": True, "葡萄牙超级杯": True,
    "比利时超级杯": True, "法国杯": True, "巴西杯": True,
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
