"""Core constants: match states, factor definitions, error codes, league rules."""

from enum import Enum


# ============================================================
# Match State Machine
# ============================================================
class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DATA_FETCHING = "DATA_FETCHING"
    DATA_READY = "DATA_READY"
    PREDICTING = "PREDICTING"
    PREDICTED = "PREDICTED"
    LOCKED = "LOCKED"
    FINISHED = "FINISHED"
    REVIEWED = "REVIEWED"
    ERROR = "ERROR"


# Valid state transitions
STATE_TRANSITIONS = {
    MatchStatus.SCHEDULED: [MatchStatus.DATA_FETCHING, MatchStatus.ERROR],
    MatchStatus.DATA_FETCHING: [MatchStatus.DATA_READY, MatchStatus.ERROR],
    MatchStatus.DATA_READY: [MatchStatus.PREDICTING, MatchStatus.ERROR],
    MatchStatus.PREDICTING: [MatchStatus.PREDICTED, MatchStatus.ERROR],
    MatchStatus.PREDICTED: [MatchStatus.PREDICTING, MatchStatus.LOCKED],
    MatchStatus.LOCKED: [MatchStatus.FINISHED],
    MatchStatus.FINISHED: [MatchStatus.REVIEWED],
    MatchStatus.REVIEWED: [],
    MatchStatus.ERROR: [MatchStatus.SCHEDULED, MatchStatus.DATA_READY],
}


# ============================================================
# Prediction Version Types
# ============================================================
class PredictionVersion(str, Enum):
    V0 = "V0"
    V_LATEST = "V_latest"
    V_HIST = "V_hist"


class TriggerReason(str, Enum):
    SCHEDULED = "scheduled"
    USER = "user"
    ODDS_JUMP = "odds_jump"
    INITIAL = "initial"


# ============================================================
# Factor Committee (F1 - F8)
# ============================================================

# Default (base) weights per factor
BASE_WEIGHTS = {
    "F1": 0.20,   # OddsPsychologist  - Claude Opus / Groq fallback
    "F2": 0.15,   # FundamentalStats - Qwen
    "F3": 0.15,   # TacticalAnalyst   - Kimi
    "F4": 0.10,   # MarketSentiment   - GPT-4o / DeepSeek fallback
    "F5": 0.10,   # HistoricalMiner   - Gemini
    "F6": 0.10,   # FitnessCycle      - DeepSeek-R1
    "F7": 0.10,   # ColdHunter        - ERNIE
    "F8": 0.10,   # EnvAnalyst        - Llama via Groq
}

# Factor definitions: id -> (name, recommended_model, specialization)
FACTOR_DEFINITIONS = {
    "F1": {
        "name": "OddsPsychologist",
        "name_cn": "首席盘口师",
        "model": "claude-opus",
        "specialization": "赔率结构、机构意图",
        "description": "识别诱盘与阻盘, 全球赔率校准度最高",
        "school": "盘口心理",
    },
    "F2": {
        "name": "FundamentalStats",
        "name_cn": "基本面统计",
        "model": "qwen-max",
        "specialization": "伤停、战意、主客场数据",
        "description": "中文语境硬数据整合, 基础事实锚点",
        "school": "硬核数据",
    },
    "F3": {
        "name": "TacticalAnalyst",
        "name_cn": "战术分析师",
        "model": "moonshot-v1-8k",
        "specialization": "阵型克制、比赛节奏",
        "description": "分析矛与盾的对决, 长文本战术理解",
        "school": "战术风格",
    },
    "F4": {
        "name": "MarketSentiment",
        "name_cn": "市场情绪师",
        "model": "gpt-4o",
        "specialization": "大众心理、热度监测",
        "description": "模拟散户行为, 作为反向指标参考",
        "school": "盘口心理",
    },
    "F5": {
        "name": "HistoricalMiner",
        "name_cn": "历史同盘矿工",
        "model": "gemini-1.5-pro",
        "specialization": "历史统计、概率回溯",
        "description": "检索历史同盘口的长期胜率",
        "school": "硬核数据",
    },
    "F6": {
        "name": "FitnessCycle",
        "name_cn": "体能周期师",
        "model": "deepseek-reasoner",
        "specialization": "赛程密度、疲劳指数",
        "description": "计算周中双赛、长途飞行后的体能临界点",
        "school": "硬核数据",
    },
    "F7": {
        "name": "ColdHunter",
        "name_cn": "冷门猎手",
        "model": "ernie-bot",
        "specialization": "意外事件、红黄牌预警",
        "description": "捕捉冷门比分, 对大热必死敏感",
        "school": "战术风格",
    },
    "F8": {
        "name": "EnvAnalyst",
        "name_cn": "环境变量师",
        "model": "llama-3.1-70b",
        "specialization": "天气、草皮、裁判",
        "description": "分析雨战、人工草皮、极端气候的影响",
        "school": "环境变量",
    },
}

# League-specific weight adjustments (applied on top of base weights)
LEAGUE_WEIGHT_RULES = {
    # Northern European leagues: Env +5%, Historical -5%
    "瑞超": {"F8": 0.05, "F5": -0.05},
    "芬超": {"F8": 0.05, "F5": -0.05},
    "挪超": {"F8": 0.05, "F5": -0.05},
    "瑞典超": {"F8": 0.05, "F5": -0.05},
    # Top 5 leagues: Fitness +5%
    "英超": {"F6": 0.05},
    "西甲": {"F6": 0.05},
    "意甲": {"F6": 0.05},
    "德甲": {"F6": 0.05},
    "法甲": {"F6": 0.05},
}

# Focus match / derby detection keywords
FOCUS_MATCH_KEYWORDS = ["德比", "焦点战", "争冠", "保级", "榜首"]


# ============================================================
# Error Taxonomy (Phase 4)
# ============================================================
ERROR_TAXONOMY = {
    "E001": {
        "code": "ERR_ODDS_MISREAD",
        "desc": "赔率解读错误(诱盘当阻盘)",
        "factor_id": "F1",
        "action": "降低该因子在特定联赛/盘口下的权重",
    },
    "E002": {
        "code": "ERR_DATA_MISSING",
        "desc": "关键数据缺失/误报",
        "factor_id": "F2",
        "action": "优化数据源或校验规则",
    },
    "E003": {
        "code": "ERR_TACTIC_MISMATCH",
        "desc": "战术克制判断失误",
        "factor_id": "F3",
        "action": "更新风格相克矩阵",
    },
    "E004": {
        "code": "ERR_SENTIMENT_WRONG",
        "desc": "市场情绪判断失误",
        "factor_id": "F4",
        "action": "调整反向指标灵敏度",
    },
    "E005": {
        "code": "ERR_HISTORICAL_BIAS",
        "desc": "历史数据过拟合",
        "factor_id": "F5",
        "action": "降低该联赛历史数据权重",
    },
    "E006": {
        "code": "ERR_FATIGUE_UNDEREST",
        "desc": "体能影响低估",
        "factor_id": "F6",
        "action": "提升体能因子权重",
    },
    "E007": {
        "code": "ERR_COLD_MISS",
        "desc": "冷门未能识别",
        "factor_id": "F7",
        "action": "提升冷门因子在焦点战的权重",
    },
    "E008": {
        "code": "ERR_ENV_IMPACT",
        "desc": "环境影响评估错误",
        "factor_id": "F8",
        "action": "提升环境因子在特定联赛权重",
    },
}

# League sensitivity multiplier (for weight penalty in iteration)
LEAGUE_SENSITIVITY = {
    "瑞超": 1.5,   # Northern European: env factor penalty doubled
    "芬超": 1.5,
    "挪超": 1.5,
    "瑞典超": 1.5,
}


# ============================================================
# Cutoff time rules
# ============================================================
WEEKDAY_CUTOFF_HOUR = 22   # Mon-Fri: 22:00
WEEKEND_CUTOFF_HOUR = 23   # Sat-Sun: 23:00

# Default leagues whitelist (FULL LIST: all supported by football-data.org free tier)
DEFAULT_LEAGUES = [
    # 五大联赛 (Europe Top 5)
    "英超", "西甲", "意甲", "德甲", "法甲",
    # 国家队赛事 (International)
    "世界杯", "世界杯预选赛(欧足联)", "世界杯预选赛(亚足联)", "世界杯预选赛(中北美)", "世界杯预选赛(南美)", "世界杯预选赛(非洲)",
    "欧洲杯", "欧洲杯预选赛", "欧国联",
    "亚洲杯", "美洲杯", "非洲杯",
    "世俱杯", "女足世界杯", "女足欧洲杯", "奥运会足球",
    # 俱乐部洲际大赛 (Club Continental)
    "欧冠", "欧联", "欧协联", "欧超杯",
    "南美解放者杯", "南美杯",
    "欧冠资格赛", "欧协联资格赛",
    # 各国顶级联赛 (Top flight per country)
    "葡超", "荷甲", "英冠",
    "巴西甲", "巴西乙",
    "俄超", "苏超", "挪超", "瑞超", "芬超",
    "希腊超", "瑞士超", "土超", "丹超", "比利时甲",
    "法乙", "德乙", "意乙", "西乙", "德丙",
    "奥超", "英甲", "英乙", "英非联", "北爱超", "威超",
    "智利甲", "秘鲁甲", "哥伦比亚甲", "阿根廷甲", "乌拉圭甲",
    "乌克兰超", "美职联", "日职联", "澳超", "墨超", "中超",
    "匈牙利甲", "罗马尼亚甲", "斯洛文尼亚甲",
    # 各国国内杯赛 (Domestic Cups)
    "英格兰足总杯", "英格兰联赛杯", "英格兰社区盾",
    "西班牙国王杯", "西班牙超级杯",
    "意大利杯", "意大利超级杯",
    "德国杯", "德国超级杯",
    "荷兰杯", "荷兰超级杯",
    "葡萄牙杯", "葡萄牙联赛杯", "葡萄牙超级杯",
    "比利时超级杯",
    "巴西杯",
]
