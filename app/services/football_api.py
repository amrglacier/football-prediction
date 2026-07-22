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

LEAGUE_MAP = {
    "英超": "Premier League",
    "西甲": "Primera Division",
    "意甲": "Serie A",
    "德甲": "Bundesliga",
    "法甲": "Ligue 1",
    "瑞超": "Allsvenskan",
    "芬超": "Veikkausliiga",
    "挪超": "Eliteserien",
}

REV_LEAGUE = {
    "Premier League": "英超", "Primera Division": "西甲", "Serie A": "意甲",
    "Bundesliga": "德甲", "Ligue 1": "法甲", "Allsvenskan": "瑞超",
    "Veikkausliiga": "芬超", "Eliteserien": "挪超",
    "La Liga": "西甲", "Spain": "西甲", "England": "英超", "Italy": "意甲",
    "Germany": "德甲", "France": "法甲", "Sweden": "瑞超", "Finland": "芬超",
    "Norway": "挪超",
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
        rev = REV_LEAGUE.get(name, name)
        for wl in whitelist:
            if name.lower() == wl.lower() or rev == wl:
                return True
            mapped = LEAGUE_MAP.get(wl, wl)
            if mapped.lower() == name.lower():
                return True
        return False

    def normalize_fixture(self, raw: dict, whitelist: list[str]) -> Optional[dict]:
        """Convert football-data.org match to internal format."""
        comp = raw.get("competition", {})
        league_name = comp.get("name", "")
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
