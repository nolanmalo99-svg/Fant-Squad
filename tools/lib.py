"""Shared helpers: env loading + ESPN client. Stdlib only, no AI calls."""
import json, os, pathlib, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# Not secret -- your league's public ESPN ID. Safe to hardcode.
LEAGUE_ID = 1090125
FIRST_SEASON = 2015


def load_env():
    """Load tools/.env into os.environ (does not override already-set vars -- CI wins)."""
    f = TOOLS / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _get(name):
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"missing env var: {name} (set it in tools/.env or GitHub secrets)")
    return v


# ---------------------------------------------------------------- ESPN

ESPN_HOST = "https://lm-api-reads.fantasy.espn.com"
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2  # seconds, doubles each retry


def _fetch_json(url, extra_headers=None):
    """GET + parse JSON, with retries for transient network errors (connection resets,
    timeouts). A 404 means "no data for this" and is not retried. A non-404 HTTP error
    (401/403/etc) means something is actually wrong (bad creds) and stops the whole run."""
    headers = {
        "Cookie": f'espn_s2={_get("ESPN_S2")}; SWID={_get("ESPN_SWID")}',
        "User-Agent": "Mozilla/5.0 (fant-squad-league-bot)",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)

    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"[espn] 404 for {url}")
                return None
            raise SystemExit(f"ESPN HTTP {e.code} {e.reason} -- creds expired? ({url})")
        except Exception as e:
            last_error = e
            print(f"[espn] attempt {attempt}/{RETRY_ATTEMPTS} failed for {url}: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF * attempt)

    print(f"[espn] giving up after {RETRY_ATTEMPTS} attempts for {url}: {last_error}")
    return None


def espn(views, season, scoring_period=None):
    q = "&".join(f"view={v}" for v in views)
    if scoring_period is not None:
        q += f"&scoringPeriodId={scoring_period}"
    url = f"{ESPN_HOST}/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{LEAGUE_ID}?{q}"
    return _fetch_json(url)


def espn_history(views, season):
    """Fallback for older seasons: ESPN's current-season endpoint only covers recent years;
    anything further back needs this separate 'leagueHistory' endpoint, same league ID."""
    q = "&".join(f"view={v}" for v in views)
    url = f"{ESPN_HOST}/apis/v3/games/ffl/leagueHistory/{LEAGUE_ID}?seasonId={season}&{q}"
    data = _fetch_json(url)
    if data is None:
        return None
    if isinstance(data, list):
        for entry in data:
            if entry.get("seasonId") == season:
                return entry
        return data[0] if data else None
    return data


def season_stats_from_player(player_stats, before_week):
    """Season-to-date total + average fantasy points, from actual (statSourceId=0) weekly lines."""
    played = [s for s in player_stats
              if s.get("statSourceId") == 0 and (s.get("scoringPeriodId") or 0) < before_week
              and (s.get("scoringPeriodId") or 0) > 0]
    if not played:
        return 0.0, 0.0, 0
    total = sum(s.get("appliedTotal", 0.0) or 0.0 for s in played)
    games = len(played)
    return round(total, 1), round(total / games, 1), games


def preseason_projection(player_stats):
    """ESPN's full-season projected total (statSourceId=1, scoringPeriodId=0), when available.
    This is what lets a draft grade exist before any games have been played."""
    for s in player_stats:
        if s.get("statSourceId") == 1 and (s.get("scoringPeriodId") in (0, None)):
            return round(s.get("appliedTotal", 0.0) or 0.0, 1)
    return None


def espn_players_by_id(season, player_ids):
    """Best-effort lookup of specific players (e.g. drafted-then-dropped) by ESPN player id.
    Falls back to the leagueHistory-style endpoint for old seasons, same as espn_history()."""
    if not player_ids:
        return []
    filt = json.dumps({"players": {"filterIds": {"value": list(player_ids)}}})

    url = f"{ESPN_HOST}/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{LEAGUE_ID}?view=kona_player_info"
    data = _fetch_json(url, extra_headers={"x-fantasy-filter": filt})
    if data and data.get("players"):
        return data["players"]

    hist_url = f"{ESPN_HOST}/apis/v3/games/ffl/leagueHistory/{LEAGUE_ID}?seasonId={season}&view=kona_player_info"
    hist_data = _fetch_json(hist_url, extra_headers={"x-fantasy-filter": filt})
    if isinstance(hist_data, list):
        for entry in hist_data:
            if entry.get("seasonId") == season and entry.get("players"):
                return entry["players"]
        return []
    return (hist_data or {}).get("players", [])


POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLOT = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "BE", 21: "IR", 23: "FLEX"}
PRO = {0:"FA",1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GB",10:"TEN",
       11:"IND",12:"KC",13:"LV",14:"LAR",15:"MIA",16:"MIN",17:"NE",18:"NO",19:"NYG",20:"NYJ",
       21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",26:"SEA",27:"TB",28:"WSH",29:"CAR",30:"JAX",
       33:"BAL",34:"HOU"}
