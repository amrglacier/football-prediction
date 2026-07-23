"""Football data API client using API-Football v3 (via RapidAPI).

API-Football v3 returns fixtures with structure:
  response[] -> fixture, league, teams, goals, score, status

Headers required:
  x-rapidapi-host: api-football-v1.p.rapidapi.com
  x-rapidapi-key: {key}
"""

import json
import logging
from datetime import date, datetime
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

# ============================================================
# LEAGUE_MAP: Chinese name -> API-Football League ID
# Organized by: 五大联赛 / 国家队赛事 / 俱乐部洲际 / 各国顶级联赛 / 各国国内杯赛
# ============================================================
LEAGUE_MAP = {
    # ====== 五大联赛 ======
    "英超": 39, "西甲": 140, "意甲": 135, "德甲": 78, "法甲": 61,
    # ====== 国家队赛事 ======
    "世界杯": 1, "世界杯预选赛(欧足联)": 31, "世界杯预选赛(亚足联)": 29,
    "世界杯预选赛(中北美)": 30, "世界杯预选赛(南美)": 28, "世界杯预选赛(非洲)": 32,
    "欧洲杯": 4, "欧洲杯预选赛": 960, "欧国联": 5,
    "亚洲杯": 34, "美洲杯": 132, "非洲杯": 36,
    "世俱杯": 15, "女足世界杯": 509, "女足欧洲杯": 447, "奥运会足球": 525,
    # ====== 俱乐部洲际大赛 ======
    "欧冠": 2, "欧联": 3, "欧协联": 848, "欧超杯": 531,
    "南美解放者杯": 13, "南美杯": 11,
    # ====== 各国顶级联赛 ======
    "葡超": 94, "荷甲": 88, "英冠": 40,
    "巴西甲": 71, "巴西乙": 72,
    "比利时甲": 144, "瑞士超": 207, "奥超": 218, "希腊超": 197,
    "土超": 203, "丹超": 119, "瑞超": 113, "芬超": 244, "挪超": 103,
    "苏超": 179, "法乙": 62, "德乙": 79, "意乙": 136, "西乙": 141,
    "德丙": 80, "英甲": 41, "英乙": 42, "英非联": 47,
    "北爱超": 149, "威超": 114, "爱尔兰超": 357,
    "冰岛超": 164, "以色列超": 383,
    "波兰超": 106, "罗马尼亚甲": 283, "克罗地亚甲": 210,
    "塞尔维亚超": 286, "斯洛伐克甲": 332, "捷克甲": 172,
    "匈牙利甲": 271, "斯洛文尼亚甲": 279,
    "乌克兰超": 333, "俄超": 235,
    "美职联": 253, "墨超": 262, "日职联": 98, "澳超": 188, "韩K联": 292,
    "中超": 169, "智利甲": 265, "阿根廷甲": 128,
    "哥伦比亚甲": 239, "乌拉圭甲": 130, "秘鲁甲": 265,
    # ====== 各国国内杯赛 ======
    "英格兰足总杯": 45, "英格兰联赛杯": 48, "英格兰社区盾": 550,
    "西班牙国王杯": 143, "西班牙超级杯": 556,
    "意大利杯": 137, "意大利超级杯": 745,
    "德国杯": 81, "德国超级杯": 529,
    "荷兰杯": 90, "荷兰超级杯": 543,
    "葡萄牙杯": 96, "葡萄牙联赛杯": 94, "葡萄牙超级杯": 532,
    "比利时超级杯": 149, "法国杯": 66, "巴西杯": 73,
}

# Reverse mapping: API-Football League ID -> Chinese name
REV_LEAGUE = {v: k for k, v in LEAGUE_MAP.items()}

# League name fallback: API English name -> Chinese name (for name-based matching)
REV_LEAGUE_NAME = {
    "Premier League": "英超", "La Liga": "西甲", "Serie A": "意甲",
    "Bundesliga": "德甲", "Ligue 1": "法甲",
    "FIFA World Cup": "世界杯", "European Championship": "欧洲杯",
    "UEFA Champions League": "欧冠", "UEFA Europa League": "欧联",
    "UEFA Conference League": "欧协联",
    "UEFA Super Cup": "欧超杯", "Copa Libertadores": "南美解放者杯",
    "Copa Sudamericana": "南美杯", "World Cup": "世界杯",
    "Primeira Liga": "葡超", "Eredivisie": "荷甲", "Championship": "英冠",
    "Campeonato Brasileiro Serie A": "巴西甲",
    "Campeonato Brasileiro Serie B": "巴西乙",
    "Scottish Premiership": "苏超", "Eliteserien": "挪超",
    "Allsvenskan": "瑞超", "Veikkausliiga": "芬超",
    "Super League": "希腊超", "Süper Lig": "土超", "Superliga": "丹超",
    "Jupiler Pro League": "比利时甲", "Ligue 2": "法乙",
    "2. Bundesliga": "德乙", "Segunda Division": "西乙",
    "3. Liga": "德丙", "League One": "英甲", "League Two": "英乙",
    "National League": "英非联", "Premiership": "北爱超",
    "Welsh Premier League": "威超",
    "Primera Division": "智利甲", "Primera A": "哥伦比亚甲",
    "Liga Profesional Argentina": "阿根廷甲",
    "Ukrainian Premier League": "乌克兰超",
    "Major League Soccer": "美职联", "J1 League": "日职联",
    "A-League": "澳超", "Liga MX": "墨超",
    "K League 1": "韩K联", "Chinese Super League": "中超",
    "NB I": "匈牙利甲", "Liga I": "罗马尼亚甲",
    "PrvaLiga": "斯洛文尼亚甲", "FA Cup": "英格兰足总杯",
    "Football League Cup": "英格兰联赛杯",
    "FA Community Shield": "英格兰社区盾",
    "Copa del Rey": "西班牙国王杯", "Coppa Italia": "意大利杯",
    "DFB Pokal": "德国杯", "KNVB Cup": "荷兰杯",
    "Taca de Portugal": "葡萄牙杯", "Copa do Brasil": "巴西杯",
}


class ApiFootballClient:
    """API-Football v3 client via RapidAPI."""

    def __init__(self):
        self.base = "https://api-football-v1.p.rapidapi.com/v3"
        self.key = settings.api_football_key
        self.host = "api-football-v1.p.rapidapi.com"
        self._ok = bool(self.key)
        self._session = requests.Session()

    def is_available(self) -> bool:
        return self._ok

    def _headers(self) -> dict:
        return {
            "x-rapidapi-key": self.key,
            "x-rapidapi-host": self.host,
            "Accept": "application/json",
        }

    def _get(self, endpoint: str, params: dict) -> dict:
        """Sync GET request to API-Football v3."""
        url = f"{self.base}/{endpoint}"
        try:
            resp = self._session.get(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                err = data["errors"]
                # Handle common errors
                if isinstance(err, dict) and err.get("token"):
                    logger.error(f"API-Football token error: {err['token']}")
                else:
                    logger.error(f"API-Football errors: {err}")
            return data
        except requests.exceptions.HTTPError as e:
            logger.error(f"API-Football HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            raise
        except Exception as e:
            logger.error(f"API-Football request error: {e}")
            raise

    def _get_fixtures(self, target_date: date, leagues: list[str]) -> list[dict]:
        """Sync: fetch matches for a date, filtered by league whitelist."""
        if not self._ok:
            return []
        d = target_date.strftime("%Y-%m-%d")
        # Resolve league IDs from whitelist
        league_ids = []
        for l in leagues:
            lid = LEAGUE_MAP.get(l)
            if lid:
                league_ids.append(lid)
            else:
                logger.warning(f"Unknown league '{l}' - no API-Football ID mapped")

        if not league_ids:
            logger.warning(f"No valid league IDs resolved from whitelist: {leagues}")
            return []

        all_matches = []
        # API-Football allows comma-separated league IDs
        ids_str = ",".join(str(x) for x in league_ids)
        try:
            data = self._get("fixtures", {"date": d, "league": ids_str, "season": target_date.year})
            matches = data.get("response", [])
            logger.info(f"Fetched {len(matches)} matches for {d} from leagues {league_ids}")
            all_matches.extend(matches)
        except Exception as e:
            logger.error(f"Failed to fetch fixtures for {d}: {e}")

        return all_matches

    async def get_fixtures(self, target_date: date, leagues: list[str]) -> list[dict]:
        """Async wrapper."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_fixtures, target_date, leagues)

    def _get_odds(self, fixture_id: str) -> Optional[dict]:
        """Sync: fetch odds for a fixture."""
        if not self._ok:
            return None
        try:
            data = self._get("odds", {"fixture": fixture_id})
            items = data.get("response", [])
            if not items:
                return None
            # Take first bookmaker's 1X2 odds
            odds_item = items[0]
            bookmakers = odds_item.get("bookmakers", [])
            if not bookmakers:
                return None
            bets = bookmakers[0].get("bets", [])
            for bet in bets:
                if bet.get("name") == "Match Winner":
                    values = bet.get("values", [])
                    h = d = a = None
                    for v in values:
                        if v.get("value") == "Home":
                            h = float(v.get("odd", 0))
                        elif v.get("value") == "Draw":
                            d = float(v.get("odd", 0))
                        elif v.get("value") == "Away":
                            a = float(v.get("odd", 0))
                    if h and d and a:
                        return {"h": h, "d": d, "a": a}
            return None
        except Exception as e:
            logger.error(f"Failed to fetch odds for {fixture_id}: {e}")
            return None

    async def get_odds(self, fixture_id: str) -> Optional[dict]:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_odds, fixture_id)

    def _get_result(self, fixture_id: str) -> Optional[dict]:
        """Sync: fetch match result by fixture ID."""
        if not self._ok:
            return None
        try:
            data = self._get("fixtures", {"id": fixture_id})
            items = data.get("response", [])
            if not items:
                return None
            f = items[0]
            status = f.get("fixture", {}).get("status", {}).get("short", "")
            if status not in ("FT", "AET", "PEN", "AWD"):
                return None
            goals = f.get("goals", {})
            hg = goals.get("home")
            ag = goals.get("away")
            if hg is None or ag is None:
                return None
            return {
                "result": "主胜" if hg > ag else "平局" if hg == ag else "客胜",
                "score": f"{hg}-{ag}",
                "home_goals": hg, "away_goals": ag,
            }
        except Exception as e:
            logger.error(f"Failed to fetch result for {fixture_id}: {e}")
            return None

    async def get_match_result(self, fixture_id: str) -> Optional[dict]:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_result, fixture_id)

    def _match_league(self, league_id: int, league_name: str, whitelist: list[str]) -> bool:
        """Check if fixture's league matches whitelist (by ID or name)."""
        # Check by league ID
        rev = REV_LEAGUE.get(league_id)
        if rev and rev in whitelist:
            return True
        # Check by league name
        rev_name = REV_LEAGUE_NAME.get(league_name, league_name)
        if rev_name in whitelist:
            return True
        # Check if any whitelist entry maps to this league ID
        for wl in whitelist:
            if LEAGUE_MAP.get(wl) == league_id:
                return True
        return False

    def normalize_fixture(self, raw: dict, whitelist: list[str]) -> Optional[dict]:
        """Convert API-Football fixture to internal format."""
        league = raw.get("league", {})
        league_id = league.get("id", 0)
        league_name = league.get("name", "")

        if not self._match_league(league_id, league_name, whitelist):
            return None

        fixture = raw.get("fixture", {})
        teams = raw.get("teams", {})
        status = fixture.get("status", {})

        home = teams.get("home", {}).get("name", "")
        away = teams.get("away", {}).get("name", "")
        mid = str(fixture.get("id", ""))
        utc = fixture.get("date", "")

        try:
            kickoff = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        except Exception:
            kickoff = datetime.utcnow()

        mdate = kickoff.date()

        # Map API-Football status to internal status
        sc = status.get("short", "")
        smap = {
            "NS": "SCHEDULED", "TBD": "SCHEDULED", "1H": "IN_PLAY",
            "HT": "IN_PLAY", "2H": "IN_PLAY", "ET": "IN_PLAY",
            "P": "IN_PLAY", "FT": "FINISHED", "AET": "FINISHED",
            "PEN": "FINISHED", "SUSP": "POSTPONED", "INT": "POSTPONED",
            "PST": "POSTPONED", "CANC": "CANCELLED", "ABD": "CANCELLED",
            "AWD": "FINISHED", "WO": "FINISHED",
        }

        return {
            "match_id": f"{mdate.strftime('%Y%m%d')}_{mid}",
            "league": REV_LEAGUE.get(league_id, REV_LEAGUE_NAME.get(league_name, league_name)),
            "home": home, "away": away,
            "kickoff": kickoff.isoformat(),
            "match_date": mdate.isoformat(),
            "api_fixture_id": mid,
            "status": smap.get(sc, "SCHEDULED"),
        }


football_client = ApiFootballClient()
