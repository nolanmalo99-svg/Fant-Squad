"""Grade each team's draft by comparing where they picked a player to how that player has
performed (or is projected to perform) relative to every other player drafted in this league.
No AI, no third-party ADP data -- just this league's own draft order vs. its own results.

Before Week 1 has been played, every player's actual total is zero, so grades would just be
ties. In that case we fall back to ESPN's own preseason full-season projection per player, and
switch over to real results automatically once games start (games_played > 0 leaguewide).
"""
from lib import espn, espn_players_by_id, season_stats_from_player, preseason_projection

GRADE_BANDS = [(0.15, "A+"), (0.35, "A"), (0.60, "B"), (0.80, "C"), (0.92, "D"), (1.01, "F")]


def _grade_for_rank_pct(pct):
    for cutoff, grade in GRADE_BANDS:
        if pct <= cutoff:
            return grade
    return "F"


def _draft_picks(season):
    d = espn(["mDraftDetail", "mSettings"], season)
    if not d:
        print("[draft] espn() returned nothing for mDraftDetail/mSettings")
        return None, None
    detail = d.get("draftDetail") or {}
    picks = detail.get("picks") or []
    print(f"[draft] drafted={detail.get('drafted')} inProgress={detail.get('inProgress')} "
          f"num_picks={len(picks)}")
    if not picks:
        return None, None
    draft_type = (d.get("settings", {}).get("draftSettings", {}) or {}).get("type", "SNAKE")
    print(f"[draft] draft_type={draft_type}, sample pick={picks[0]}")
    return picks, draft_type


def build_draft_grades(season, standings_with_roster, current_week):
    """standings_with_roster: league.build_all_weeks()['standings'] (includes 'roster' + 'team_id')."""
    picks, draft_type = _draft_picks(season)
    if not picks:
        return None

    # league-wide player pool from everyone's current roster (covers anyone still on a team)
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

    # any drafted player not found above was drafted-then-dropped; best-effort fetch their stats
    missing_ids = [pk.get("playerId") for pk in picks if pk.get("playerId") not in pool]
    missing_ids = [pid for pid in missing_ids if pid]
    if missing_ids:
        fetched = espn_players_by_id(season, missing_ids)
        for entry in fetched:
            pl = entry.get("player", entry) or {}
            pid = pl.get("id") or entry.get("id")
            if not pid:
                continue
            total, _, gp = season_stats_from_player(pl.get("stats", []), current_week)
            pool[pid] = {
                "name": pl.get("fullName", f"Player #{pid}"), "pos": "?", "pro": "?",
                "season_total": total, "games_played": gp,
                "preseason_proj_total": preseason_projection(pl.get("stats", [])),
                "dropped": True,
            }
    for pid in missing_ids:
        if pid not in pool:
            pool[pid] = {"name": f"Player #{pid}", "pos": "?", "pro": "?",
                         "season_total": 0.0, "games_played": 0,
                         "preseason_proj_total": None, "dropped": True}

    # preseason (no games played anywhere yet) -> grade on ESPN's projections instead of results
    total_games_played = sum(info.get("games_played", 0) for info in pool.values())
    mode = "actual" if total_games_played > 0 else "projected"

    def _value(info):
        if mode == "actual":
            return info.get("season_total", 0.0) or 0.0
        return info.get("preseason_proj_total") or info.get("season_total", 0.0) or 0.0

    # expected-value baseline: bid amount for auctions (higher = better), pick order for snake/linear
    is_auction = (draft_type or "").upper() == "AUCTION"
    if is_auction:
        ranked_picks = sorted(picks, key=lambda pk: -(pk.get("bidAmount") or 0))
    else:
        ranked_picks = sorted(picks, key=lambda pk: pk.get("overallPickNumber") or 0)
    for i, pk in enumerate(ranked_picks):
        pk["_expected_rank"] = i + 1

    # actual/projected-value ranking: sort every drafted player by the chosen value metric
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

    team_id_to_guid = {t["team_id"]: t["guid"] for t in standings_with_roster if t.get("team_id")}

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
