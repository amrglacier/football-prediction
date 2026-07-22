"""Football data API client using football-data.org (free, China-accessible).

Uses urllib for synchronous requests to avoid async/SSL issues.
"""

import json
import logging
import urllib.request
from datetime import date, datetime
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# ============================================================
# LEAGUE_MAP: Chinese name -> API English name
# Organized by: 五大联赛 / 国家队赛事 / 俱乐部洲际 / 各国顶级联赛 / 各国国内杯赛
# ============================================================
LEAGUE_MAP = {
    # ====== 五大联赛 ======
    "英超": "Premier League",
    "西甲": "Primera Division",
    "意甲": "Serie A",
    "德甲": "Bundesliga",
    "法甲": "Ligue 1",
    # ====== 国家队赛事 ======
    "世界杯": "FIFA World Cup",
    "世界杯预选赛(欧足联)": "WC Qualification UEFA",
    "世界杯预选赛(亚足联)": "WC Qualification AFC",
    "世界杯预选赛(中北美)": "WC Qualification CONCACAF",
    "世界杯预选赛(南美)": "WC Qualification CONMEBOL",
    "世界杯预选赛(非洲)": "WC Qualification CAF",
    "欧洲杯": "European Championship",
    "欧洲杯预选赛": "European Championship Qualifiers",
    "欧国联": "UEFA Nations League",
    "亚洲杯": "AFC Asian Cup",
    "美洲杯": "Copa America",
    "非洲杯": "Africa Cup",
    "世俱杯": "FIFA Club World Cup",
    "女足世界杯": "FIFA Women's World Cup",
    "女足欧洲杯": "UEFA Women's Euro",
    "奥运会足球": "Summer Olympics",
    # ====== 俱乐部洲际大赛 ======
    "欧冠": "UEFA Champions League",
    "欧联": "UEFA Europa League",
    "欧协联": "UEFA Conference League",
    "欧超杯": "UEFA Super Cup",
    "南美解放者杯": "Copa Libertadores",
    "南美杯": "Copa Sudamericana",
    "欧冠资格赛": "Champions League Qualification",
    "欧协联资格赛": "Conference League Qualification",
    # ====== 各国顶级联赛 ======
    "葡超": "Primeira Liga",
    "荷甲": "Eredivisie",
    "英冠": "Championship",
    "巴西甲": "Campeonato Brasileiro Série A",
    "巴西乙": "Campeonato Brasileiro Série B",
    "俄超": "RFPL",
    "苏超": "Scottish Premier League",
    "挪超": "Eliteserien",
    "瑞超": "Allsvenskan",
    "芬超": "Veikkausliiga",
    "希腊超": "Super League",
    "瑞士超": "Super League",
    "土超": "Süper Lig",
    "丹超": "Superliga",
    "比利时甲": "Jupiler Pro League",
    "法乙": "Ligue 2",
    "德乙": "2. Bundesliga",
    "意乙": "Serie B",
    "西乙": "Segunda División",
    "德丙": "3. Bundesliga",
    "奥超": "Bundesliga",
    "英甲": "League One",
    "英乙": "League Two",
    "英非联": "National League",
    "北爱超": "Premiership",
    "威超": "Welsh Premier League",
    "智利甲": "Primera División",
    "秘鲁甲": "Primera División",
    "哥伦比亚甲": "Primera A",
    "阿根廷甲": "Liga Profesional",
    "乌拉圭甲": "Primera División",
    "乌克兰超": "Premier Liha",
    "美职联": "MLS",
    "日职联": "J. League",
    "澳超": "A League",
    "墨超": "Liga MX",
    "中超": "Chinese Super League",
    "匈牙利甲": "NB I",
    "罗马尼亚甲": "Liga I",
    "斯洛文尼亚甲": "PrvaLiga",
    # ====== 各国国内杯赛 ======
    "英格兰足总杯": "FA Cup",
    "英格兰联赛杯": "Football League Cup",
    "英格兰社区盾": "FA Community Shield",
    "西班牙国王杯": "Copa del Rey",
    "西班牙超级杯": "Supercopa de España",
    "意大利杯": "Coppa Italia",
    "意大利超级杯": "Supercoppa",
    "德国杯": "DFB-Pokal",
    "德国超级杯": "DFL Super Cup",
    "荷兰杯": "KNVB Beker",
    "荷兰超级杯": "Johan Cruijff Schaal",
    "葡萄牙杯": "Taça de Portugal",
    "葡萄牙联赛杯": "Taça da Liga",
    "葡萄牙超级杯": "Supertaça Cândido de Oliveira",
    "比利时超级杯": "Supercoupe de Belgique",
    "巴西杯": "Copa do Brasil",
}

# ============================================================
# REV_LEAGUE: API English name -> Chinese name (used for reverse lookup)
# NOTE: Keys are the league names as returned by football-data.org API.
# ============================================================
REV_LEAGUE = {
    # 五大联赛
    "Premier League": "英超", "Primera Division": "西甲", "Serie A": "意甲",
    "Bundesliga": "德甲", "Ligue 1": "法甲",
    # 国家队赛事
    "FIFA World Cup": "世界杯",
    "WC Qualification UEFA": "世界杯预选赛(欧足联)",
    "WC Qualification AFC": "世界杯预选赛(亚足联)",
    "WC Qualification CONCACAF": "世界杯预选赛(中北美)",
    "WC Qualification CONMEBOL": "世界杯预选赛(南美)",
    "WC Qualification CAF": "世界杯预选赛(非洲)",
    "European Championship": "欧洲杯",
    "European Championship Qualifiers": "欧洲杯预选赛",
    "UEFA Nations League": "欧国联",
    "AFC Asian Cup": "亚洲杯",
    "Copa America": "美洲杯",
    "Africa Cup": "非洲杯",
    "FIFA Club World Cup": "世俱杯",
    "FIFA Women's World Cup": "女足世界杯",
    "UEFA Women's Euro": "女足欧洲杯",
    "Summer Olympics": "奥运会足球",
    # 俱乐部洲际
    "UEFA Champions League": "欧冠",
    "UEFA Europa League": "欧联",
    "UEFA Conference League": "欧协联",
    "UEFA Super Cup": "欧超杯",
    "Copa Libertadores": "南美解放者杯",
    "Copa Sudamericana": "南美杯",
    "Champions League Qualification": "欧冠资格赛",
    "Conference League Qualification": "欧协联资格赛",
    # 各国顶级联赛
    "Primeira Liga": "葡超", "Eredivisie": "荷甲", "Championship": "英冠",
    "Campeonato Brasileiro Série A": "巴西甲",
    "Campeonato Brasileiro Série B": "巴西乙",
    "RFPL": "俄超", "Scottish Premier League": "苏超",
    "Eliteserien": "挪超", "Tippeligaen": "挪超",
    "Allsvenskan": "瑞超", "Veikkausliiga": "芬超",
    "Super League": "希腊超", "Süper Lig": "土超", "Superliga": "丹超",
    "Jupiler Pro League": "比利时甲", "Ligue 2": "法乙",
    "2. Bundesliga": "德乙", "Serie B": "意乙", "Segunda División": "西乙",
    "3. Bundesliga": "德丙", "League One": "英甲", "League Two": "英乙",
    "National League": "英非联", "Premiership": "北爱超",
    "Welsh Premier League": "威超",
    "Primera División": "智利甲", "Primera A": "哥伦比亚甲",
    "Liga Profesional": "阿根廷甲",
    "Premier Liha": "乌克兰超", "MLS": "美职联", "J. League": "日职联",
    "A League": "澳超", "Liga MX": "墨超", "Chinese Super League": "中超",
    "NB I": "匈牙利甲", "Liga I": "罗马尼亚甲", "PrvaLiga": "斯洛文尼亚甲",
    "Playoffs 1/2": "土伦杯", "Austria": "奥超",
    # Country-based aliases (fallback for _match_league)
    "Norway": "挪超", "Sweden": "瑞超", "Finland": "芬超",
    "England": "英超", "Germany": "德甲", "Spain": "西甲",
    "Italy": "意甲", "France": "法甲", "Portugal": "葡超",
    "Netherlands": "荷甲", "Brazil": "巴西甲", "Russia": "俄超",
    "Greece": "希腊超", "Switzerland": "瑞士超", "Turkey": "土超",
    "Denmark": "丹超", "Belgium": "比利时甲", "China": "中超",
    "USA": "美职联", "Australia": "澳超", "Japan": "日职联",
    "Mexico": "墨超", "Scotland": "苏超", "Wales": "威超",
    "Ukraine": "乌克兰超", "Chile": "智利甲", "Argentina": "阿根廷甲",
    "Uruguay": "乌拉圭甲", "Colombia": "哥伦比亚甲", "Peru": "秘鲁甲",
    "Romania": "罗马尼亚甲", "Hungary": "匈牙利甲", "Slovenia": "斯洛文尼亚甲",
    "Northern Ireland": "北爱超",
    # 各国国内杯赛
    "FA Cup": "英格兰足总杯", "Football League Cup": "英格兰联赛杯",
    "FA Community Shield": "英格兰社区盾", "Copa del Rey": "西班牙国王杯",
    "Supercopa de España": "西班牙超级杯", "Coppa Italia": "意大利杯",
    "Supercoppa": "意大利超级杯", "DFB-Pokal": "德国杯",
    "DFL Super Cup": "德国超级杯", "Coupe de France": "法国杯",
    "KNVB Beker": "荷兰杯", "Johan Cruijff Schaal": "荷兰超级杯",
    "Taça de Portugal": "葡萄牙杯", "Taça da Liga": "葡萄牙联赛杯",
    "Supertaça Cândido de Oliveira": "葡萄牙超级杯",
    "Supercoupe de Belgique": "比利时超级杯", "Copa do Brasil": "巴西杯",
}


def _req(url: str, token: str) -> dict:
    """Synchronous GET request with X-Auth-Token header."""
    req = urllib.request.Request(url, headers={
        "X-Auth-Token": token,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


class FootballDataClient:
    def __init__(self):
        self.base = "https://api.football-data.org/v4"
        self.key = settings.api_football_key
        self._ok = bool(self.key)

    def is_available(self) -> bool:
        return self._ok

    def _get_fixtures(self, target_date: date, leagues: list[str]) -> list[dict]:
        """Sync: fetch matches for a date."""
        if not self._ok:
            return []
        d = target_date.strftime("%Y-%m-%d")
        try:
            data = _req(f"{self.base}/matches?dateFrom={d}&dateTo={d}", self.key)
            matches = data.get("matches", [])
            logger.info(f"Fetched {len(matches)} matches for {d}")
            return matches
        except Exception as e:
            logger.error(f"Failed to fetch fixtures: {e}")
            return []

    async def get_fixtures(self, target_date: date, leagues: list[str]) -> list[dict]:
        """Async wrapper around sync _get_fixtures."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_fixtures, target_date, leagues)

    def _get_odds(self, fixture_id: str) -> Optional[dict]:
        """Free tier has no odds."""
        return None

    async def get_odds(self, fixture_id: str) -> Optional[dict]:
        return self._get_odds(fixture_id)

    def _get_result(self, fixture_id: str) -> Optional[dict]:
        """Sync: fetch match result."""
        if not self._ok:
            return None
        try:
            data = _req(f"{self.base}/matches/{fixture_id}", self.key)
            m = data.get("match", {})
            if not m or m.get("status") not in ("FINISHED", "AWARDED"):
                return None
            ft = m.get("score", {}).get("fullTime", {})
            hg, ag = ft.get("home"), ft.get("away")
            if hg is None or ag is None:
                return None
            return {
                "result": "主胜" if hg > ag else "平局" if hg == ag else "客胜",
                "score": f"{hg}-{ag}",
                "home_goals": hg, "away_goals": ag,
            }
        except Exception as e:
            logger.error(f"Failed to fetch result: {e}")
            return None

    async def get_match_result(self, fixture_id: str) -> Optional[dict]:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_result, fixture_id)

    def _match_league(self, name: str, whitelist: list[str]) -> bool:
        """Check if API league name matches whitelist."""
        # Direct reverse mapping
        rev = REV_LEAGUE.get(name, name)
        if rev in whitelist:
            return True
        # Check whitelist entry matches mapped English name
        for wl in whitelist:
            if name.lower() == wl.lower():
                return True
            mapped = LEAGUE_MAP.get(wl, wl)
            if mapped.lower() == name.lower():
                return True
        return False

    def normalize_fixture(self, raw: dict, whitelist: list[str]) -> Optional[dict]:
        """Convert football-data.org match to internal format."""
        comp = raw.get("competition", {})
        league_name = comp.get("name", "")
        area = comp.get("area", {}).get("name", "")
        if not self._match_league(league_name, whitelist):
            return None

        home = raw.get("homeTeam", {}).get("name", "")
        away = raw.get("awayTeam", {}).get("name", "")
        mid = str(raw.get("id", ""))
        utc = raw.get("utcDate", "")

        try:
            kickoff = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        except Exception:
            kickoff = datetime.utcnow()

        mdate = kickoff.date()
        smap = {
            "SCHEDULED": "SCHEDULED", "LIVE": "IN_PLAY", "IN_PLAY": "IN_PLAY",
            "PAUSED": "IN_PLAY", "FINISHED": "FINISHED", "POSTPONED": "POSTPONED",
            "CANCELLED": "CANCELLED", "AWARDED": "FINISHED",
        }

        return {
            "match_id": f"{mdate.strftime('%Y%m%d')}_{mid}",
            "league": REV_LEAGUE.get(league_name, league_name),
            "home": home, "away": away,
            "kickoff": kickoff.isoformat(),
            "match_date": mdate.isoformat(),
            "api_fixture_id": mid,
            "status": smap.get(raw.get("status", ""), "SCHEDULED"),
        }


football_client = FootballDataClient()
