"""Grade each team's draft by comparing where they picked a player to how that player has
performed (or is projected to perform) relative to every other player drafted in this league.
No AI, no third-party ADP data -- just this league's own draft order vs. its own results.

Current season: before Week 1 has been played, every player's actual total is zero, so grades
would just be ties. In that case we fall back to ESPN's own preseason full-season projection
per player, and switch over to real results automatically once games start.

Past seasons: always graded on actual full-season production. The main risk is a drafted
player who was dropped mid-season in a *past* year -- we try a best-effort stats lookup, but
if ESPN's players-by-id endpoint doesn't serve historical seasons well, that pick degrades
gracefully to "stats unavailable" rather than breaking the whole season's grades.
"""
from lib import espn, espn_history, espn_players_by_id, season_stats_from_player, preseason_projection, POS, PRO

GRADE_BANDS = [(0.15, "A+"), (0.35, "A"), (0.60, "B"), (0.80, "C"), (0.92, "D"), (1.01, "F")]


def _grade_for_rank_pct(pct):
    for cutoff, grade in GRADE_BANDS:
        if pct <= cutoff:
            return grade
    return "F"


def _draft_picks(season):
    d = espn(["mDraftDetail", "mSettings"], season)
    if not d or not (d.get("draftDetail") or {}).get("picks"):
        d = espn_history(["mDraftDetail", "mSettings"], season)
    if not d:
        print(f"[draft] season {season}: no response from either endpoint")
        return None, None
    detail = d.get("draftDetail") or {}
    picks = detail.get("picks") or []
    print(f"[draft] season {season}: drafted={detail.get('drafted')} num_picks={len(picks)}")
    if not picks:
        return None, None
    draft_type = (d.get("settings", {}).get("draftSettings", {}) or {}).get("type", "SNAKE")
    return picks, draft_type


def _team_id_to_guid(teams_raw):
    out = {}
    for t in teams_raw:
        guid = t.get("primaryOwner") or (t.get("owners") or [None])[0]
        if guid:
            out[t["id"]] = guid
    return out


def _grade_picks(picks, draft_type, pool, team_id_to_guid, mode):
    """Shared scoring core, used for both the live current season and historical seasons."""
    def _value(info):
        if mode == "actual":
            return info.get("season_total", 0.0) or 0.0
        return info.get("preseason_proj_total") or info.get("season_total", 0.0) or 0.0

    is_auction = (draft_type or "").upper() == "AUCTION"
    if is_auction:
        ranked_picks = sorted(picks, key=lambda pk: -(pk.get("bidAmount") or 0))
    else:
        ranked_picks = sorted(picks, key=lambda pk: pk.get("overallPickNumber") or 0)
    for i, pk in enumerate(ranked_picks):
        pk["_expected_rank"] = i + 1

    perf_ranked = sorted(picks, key=lambda pk: -_value(pool.get(pk.get("playerId"), {})))
    for i, pk in enumerate(perf_ranked):
        pk["_performance_rank"] = i + 1

    for pk in picks:
        pk["_value_diff"] = pk["_expected_rank"] - pk["_performance_rank"]
        info = pool.get(pk.get("playerId"), {})
        pk["_name"] = info.get("name", "Unknown")
        pk["_pos"] = info.get("pos", "?")
        pk["_pro"] = info.get("pro", "?")
        pk["_points"] = round(_value(info), 1)
        pk["_dropped"] = info.get("dropped", False)

    by_team = {}
    for pk in picks:
        by_team.setdefault(pk.get("teamId"), []).append(pk)

    team_scores = {}
    for team_id, team_picks in by_team.items():
        team_scores[team_id] = sum(pk["_value_diff"] for pk in team_picks) / max(len(team_picks), 1)

    ranked_teams = sorted(team_scores.keys(), key=lambda tid: -team_scores[tid])
    n_teams = max(len(ranked_teams), 1)

    results = {}
    for rank, team_id in enumerate(ranked_teams):
        team_picks = sorted(by_team[team_id],
                             key=lambda pk: (pk.get("roundId") or 0, pk.get("roundPickNumber") or 0))
        best = max(team_picks, key=lambda pk: pk["_value_diff"])
        worst = min(team_picks, key=lambda pk: pk["_value_diff"])
        pct = rank / (n_teams - 1) if n_teams > 1 else 0
        guid = team_id_to_guid.get(team_id)
        if not guid:
            continue

        def pick_out(pk):
            return {
                "name": pk["_name"], "pos": pk["_pos"], "pro": pk["_pro"],
                "round": pk.get("roundId"), "pick_in_round": pk.get("roundPickNumber"),
                "overall_pick": pk.get("overallPickNumber"),
                "bid_amount": pk.get("bidAmount") if is_auction else None,
                "points": pk["_points"], "value_diff": pk["_value_diff"],
                "dropped": pk["_dropped"],
            }

        results[guid] = {
            "grade": _grade_for_rank_pct(pct),
            "league_rank": rank + 1,
            "league_size": n_teams,
            "draft_type": draft_type,
            "mode": mode,
            "best_pick": pick_out(best),
            "worst_pick": pick_out(worst),
            "picks": [pick_out(pk) for pk in team_picks],
        }
    return results


def _refine_with_global_lookup(season, pool, player_ids, cutoff_week):
    """The stats embedded in a team's roster snapshot can be scoped to only the weeks a player
    was on THAT team -- if they were traded, dropped-and-repicked, or streamed off waivers, that
    undercounts their real season. The kona_player_info lookup returns the player's global stat
    line regardless of roster history, so we prefer it whenever it's higher than what we already
    have. This never makes a number worse: pool totals only ever go up from this."""
    player_ids = [pid for pid in player_ids if pid]
    if not player_ids:
        return
    fetched = espn_players_by_id(season, player_ids)
    if not fetched:
        return
    corrected = 0
    for entry in fetched:
        pl = entry.get("player", entry) or {}
        pid = pl.get("id") or entry.get("id")
        if not pid:
            continue
        total, _, gp = season_stats_from_player(pl.get("stats", []), cutoff_week)
        existing = pool.get(pid)
        if existing is None:
            pool[pid] = {
                "name": pl.get("fullName", f"Player #{pid}"), "pos": "?", "pro": "?",
                "season_total": total, "games_played": gp,
                "preseason_proj_total": preseason_projection(pl.get("stats", [])),
                "dropped": True,
            }
        elif total > existing.get("season_total", 0.0):
            corrected += 1
            existing["season_total"] = total
            existing["games_played"] = max(existing.get("games_played", 0), gp)
            if existing.get("name", "").startswith("Player #"):
                existing["name"] = pl.get("fullName", existing["name"])
    if corrected:
        print(f"[draft] season {season}: global lookup corrected {corrected} truncated/roster-scoped "
              f"player totals (mid-season trade/waiver moves)")


def build_draft_grades(season, standings_with_roster, current_week):
    """Live grading for the current season. standings_with_roster:
    league.build_all_weeks()['standings'] (includes 'roster' + 'team_id')."""
    picks, draft_type = _draft_picks(season)
    if not picks:
        return None

    pool = {}
    for t in standings_with_roster:
        for p in t.get("roster", []):
            if p.get("player_id"):
                pool[p["player_id"]] = {
                    "name": p["name"], "pos": p["pos"], "pro": p["pro"],
                    "season_total": p["season_total"], "games_played": p.get("games_played", 0),
                    "preseason_proj_total": p.get("preseason_proj_total"),
                    "dropped": False,
                }

    all_ids = [pk.get("playerId") for pk in picks if pk.get("playerId")]
    _refine_with_global_lookup(season, pool, all_ids, current_week)

    for pid in all_ids:
        if pid not in pool:
            pool[pid] = {"name": f"Player #{pid}", "pos": "?", "pro": "?",
                         "season_total": 0.0, "games_played": 0,
                         "preseason_proj_total": None, "dropped": True}

    total_games_played = sum(info.get("games_played", 0) for info in pool.values())
    mode = "actual" if total_games_played > 0 else "projected"

    team_id_to_guid = {t["team_id"]: t["guid"] for t in standings_with_roster if t.get("team_id")}
    return _grade_picks(picks, draft_type, pool, team_id_to_guid, mode)


def _historical_player_pool(season):
    """End-of-season rosters for a past season -> {player_id: {name, pos, pro, season_total, ...}}.
    Covers anyone still on a roster when the season ended; drafted-then-dropped players need the
    best-effort lookup below."""
    d = espn(["mTeam", "mRoster", "mSettings"], season)
    if not d or not d.get("teams"):
        d = espn_history(["mTeam", "mRoster", "mSettings"], season)
    if not d or not d.get("teams"):
        print(f"[draft] season {season}: no roster data from either endpoint")
        return {}, {}

    matchup_period_count = d.get("settings", {}).get("scheduleSettings", {}).get("matchupPeriodCount", 17)
    cutoff_week = matchup_period_count + 10  # season is over; count every week played

    pool = {}
    for t in d.get("teams", []):
        roster = (t.get("roster") or {}).get("entries", [])
        for e in roster:
            pl = e.get("playerPoolEntry", {}).get("player", {})
            pid = pl.get("id")
            if not pid:
                continue
            total, _, gp = season_stats_from_player(pl.get("stats", []), cutoff_week)
            pool[pid] = {
                "name": pl.get("fullName", f"Player #{pid}"),
                "pos": POS.get(pl.get("defaultPositionId"), "?"),
                "pro": PRO.get(pl.get("proTeamId"), "?"),
                "season_total": total, "games_played": gp, "dropped": False,
            }
    print(f"[draft] season {season}: end-of-season roster pool has {len(pool)} players")
    return pool, _team_id_to_guid(d.get("teams", []))


def build_historical_draft_grades(first_season, last_completed_season):
    """Grades for every fully-completed past season. Returns {season: {guid: grade_dict}}."""
    all_results = {}
    for season in range(first_season, last_completed_season + 1):
        picks, draft_type = _draft_picks(season)
        if not picks:
            continue

        pool, team_id_to_guid = _historical_player_pool(season)
        if not pool:
            continue

        all_ids = [pk.get("playerId") for pk in picks if pk.get("playerId")]
        missing_before = len([pid for pid in all_ids if pid not in pool])
        _refine_with_global_lookup(season, pool, all_ids, 999)
        if missing_before:
            print(f"[draft] season {season}: {missing_before} drafted-then-dropped players in the lookup")

        for pid in all_ids:
            if pid not in pool:
                pool[pid] = {"name": f"Player #{pid}", "pos": "?", "pro": "?",
                             "season_total": 0.0, "games_played": 0, "dropped": True}

        season_results = _grade_picks(picks, draft_type, pool, team_id_to_guid, mode="actual")
        if season_results:
            all_results[season] = season_results

    return all_results
