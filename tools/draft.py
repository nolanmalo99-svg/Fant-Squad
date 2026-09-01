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
    """Best-effort stats lookup for players not found in any team's roster/schedule data --
    typically someone drafted and then dropped for good, never picked up by anyone else. This
    endpoint (kona_player_info) reliably covers free agents, which is exactly this case; it does
    NOT reliably return full-season data for players who are actively rostered, so this should
    only ever be called with players missing from the pool, not to "correct" existing entries."""
    player_ids = [pid for pid in player_ids if pid]
    if not player_ids:
        return
    fetched = espn_players_by_id(season, player_ids)
    if not fetched:
        return
    found = 0
    for entry in fetched:
        pl = entry.get("player", entry) or {}
        pid = pl.get("id") or entry.get("id")
        if not pid or pid in pool:
            continue
        total, _, gp = season_stats_from_player(pl.get("stats", []), cutoff_week)
        pool[pid] = {
            "name": pl.get("fullName", f"Player #{pid}"), "pos": "?", "pro": "?",
            "season_total": total, "games_played": gp,
            "preseason_proj_total": preseason_projection(pl.get("stats", [])),
            "dropped": True,
        }
        found += 1
    print(f"[draft] season {season}: {len(player_ids)} players missing from any roster, "
          f"best-effort lookup found {found}")


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

    missing_ids = [pk.get("playerId") for pk in picks if pk.get("playerId") not in pool]
    missing_ids = [pid for pid in missing_ids if pid]
    _refine_with_global_lookup(season, pool, missing_ids, current_week)

    for pid in missing_ids:
        if pid not in pool:
            pool[pid] = {"name": f"Player #{pid}", "pos": "?", "pro": "?",
                         "season_total": 0.0, "games_played": 0,
                         "preseason_proj_total": None, "dropped": True}

    total_games_played = sum(info.get("games_played", 0) for info in pool.values())
    mode = "actual" if total_games_played > 0 else "projected"

    team_id_to_guid = {t["team_id"]: t["guid"] for t in standings_with_roster if t.get("team_id")}
    return _grade_picks(picks, draft_type, pool, team_id_to_guid, mode)


def _historical_player_pool(season):
    """Build a player pool from every WEEK's matchup-embedded roster across a past season,
    rather than a single end-of-season snapshot. This is the same technique league.py already
    uses successfully for the live season -- each week's roster carries that week's actual stat
    line, so a player's full season adds up correctly even if they were traded, dropped, or
    picked up off waivers partway through (an end-of-season-only snapshot would miss all of
    that, undercounting anyone who changed hands)."""
    d = espn(["mTeam", "mSettings", "mMatchupScore", "mRoster", "mScoreboard"], season)
    if not d or not d.get("teams"):
        d = espn_history(["mTeam", "mSettings", "mMatchupScore", "mRoster", "mScoreboard"], season)
    if not d or not d.get("teams"):
        print(f"[draft] season {season}: no roster data from either endpoint")
        return {}, {}

    teams_raw = d.get("teams", [])
    pool = {}
    weeks_seen = {}  # player_id -> set of scoringPeriodIds already counted, to avoid double-counting
    schedule = d.get("schedule", [])

    for s in schedule:
        wk = s.get("matchupPeriodId")
        for side_key in ("home", "away"):
            side = s.get(side_key)
            if not side:
                continue
            roster = (side.get("rosterForMatchupPeriod") or side.get("rosterForCurrentScoringPeriod") or {})
            for e in roster.get("entries", []):
                pl = e.get("playerPoolEntry", {}).get("player", {})
                pid = pl.get("id")
                if not pid:
                    continue
                week_pts = None
                for stat in pl.get("stats", []):
                    if stat.get("statSourceId") == 0 and stat.get("scoringPeriodId") == wk:
                        week_pts = stat.get("appliedTotal", 0.0) or 0.0
                        break
                if week_pts is None:
                    continue  # bye week or no stat line recorded for this week
                seen = weeks_seen.setdefault(pid, set())
                if wk in seen:
                    continue  # already counted this week for this player (e.g. seen via both sides)
                seen.add(wk)
                entry = pool.setdefault(pid, {
                    "name": pl.get("fullName", f"Player #{pid}"),
                    "pos": POS.get(pl.get("defaultPositionId"), "?"),
                    "pro": PRO.get(pl.get("proTeamId"), "?"),
                    "season_total": 0.0, "games_played": 0, "dropped": False,
                })
                entry["season_total"] = round(entry["season_total"] + week_pts, 1)
                entry["games_played"] += 1

    print(f"[draft] season {season}: week-by-week roster pool has {len(pool)} players "
          f"(from {len(schedule)} scheduled matchups)")
    return pool, _team_id_to_guid(teams_raw)


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
        missing_ids = [pid for pid in all_ids if pid not in pool]
        _refine_with_global_lookup(season, pool, missing_ids, 999)

        for pid in missing_ids:
            if pid not in pool:
                pool[pid] = {"name": f"Player #{pid}", "pos": "?", "pro": "?",
                             "season_total": 0.0, "games_played": 0, "dropped": True}

        season_results = _grade_picks(picks, draft_type, pool, team_id_to_guid, mode="actual")
        if season_results:
            all_results[season] = season_results

    return all_results
