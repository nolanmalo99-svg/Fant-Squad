"""Normalize the ESPN league payload into matchup data for every week of a season,
in a single API call. Pure stats -- no AI-generated copy, just facts."""
from lib import espn, POS, SLOT, PRO, season_stats_from_player, preseason_projection

STARTER_SLOTS = set(SLOT) - {20, 21}  # everything except BE / IR
BENCH_SLOT = 20
HEALTHY = {"ACTIVE", "NORMAL", None}


def _proj_and_actual(entry, scoring_period):
    proj = actual = 0.0
    p = entry.get("playerPoolEntry", {}).get("player", {})
    for s in p.get("stats", []):
        if s.get("scoringPeriodId") != scoring_period:
            continue
        if s.get("statSourceId") == 0:
            actual = s.get("appliedTotal", 0.0) or 0.0
        elif s.get("statSourceId") == 1:
            proj = s.get("appliedTotal", 0.0) or 0.0
    return round(proj, 1), round(actual, 1)


def _side(raw_side, teams, scoring_period):
    tid = raw_side["teamId"]
    t = teams.get(tid, {"name": "?", "owner": "?", "record": "0-0", "guid": None})
    roster = (raw_side.get("rosterForCurrentScoringPeriod")
              or raw_side.get("rosterForMatchupPeriod") or {})
    starters, bench_proj = [], 0.0
    for e in roster.get("entries", []):
        slot = e.get("lineupSlotId")
        pl = e.get("playerPoolEntry", {}).get("player", {})
        proj, act = _proj_and_actual(e, scoring_period)
        if slot == BENCH_SLOT:
            bench_proj += proj
            continue
        if slot not in STARTER_SLOTS:
            continue
        starters.append({
            "name": pl.get("fullName", "?"), "slot": SLOT.get(slot, str(slot)),
            "pos": POS.get(pl.get("defaultPositionId"), "?"),
            "pro": PRO.get(pl.get("proTeamId"), "?"),
            "proj": proj, "actual": act,
            "injury": pl.get("injuryStatus") if pl.get("injuryStatus") not in HEALTHY else None,
        })
    proj_total = sum(s["proj"] for s in starters)
    return {
        "teamId": tid, "guid": t.get("guid"), "team": t["name"], "owner": t["owner"], "record": t["record"],
        "actual": round(raw_side.get("totalPoints", 0.0), 1),
        "projected": round(raw_side.get("totalProjectedPointsLive") or proj_total, 1),
        "starters": starters,
        "bench_proj": round(bench_proj, 1),
        "injuries": [s for s in starters if s["injury"]],
    }


def _owner_name(members, guid):
    for m in members:
        if m.get("id") == guid:
            fn, ln = (m.get("firstName") or "").strip(), (m.get("lastName") or "").strip()
            return f"{fn} {ln}".strip() or m.get("displayName", guid)
    return guid


def _blurb(m, phase):
    """Plain stat-based summary, no AI."""
    a, h = m["away"], m["home"]
    if phase == "preview":
        fav = a if a["projected"] > h["projected"] else h
        return (f"{a['owner']} ({a['record']}) at {h['owner']} ({h['record']}). "
                f"Projected: {a['owner']} {a['projected']} - {h['owner']} {h['projected']}. "
                f"{fav['owner']} favored by {round(abs(a['projected']-h['projected']),1)}.")
    winner, loser = (h, a) if h["actual"] > a["actual"] else (a, h)
    top = sorted(winner["starters"], key=lambda s: -s["actual"])[:2]
    top_txt = ", ".join(f'{s["name"]} ({s["actual"]})' for s in top)
    return (f"Final: {a['owner']} {a['actual']} - {h['owner']} {h['actual']}. "
            f"{winner['owner']} won by {round(abs(h['actual']-a['actual']),1)}. "
            f"Top scorers for {winner['owner']}: {top_txt}.")


def _team_form(team_games, team_id, before_week, n=3):
    """Trailing record/avg/streak for a team using only games played before `before_week`."""
    hist = [g for g in team_games.get(team_id, []) if g["week"] < before_week]
    if not hist:
        return None
    season_avg = round(sum(g["pts"] for g in hist) / len(hist), 1)
    recent = hist[-n:]
    recent_avg = round(sum(g["pts"] for g in recent) / len(recent), 1)
    wins = sum(1 for g in recent if g["win"])
    streak_result = hist[-1]["win"]
    streak = 1
    for g in reversed(hist[:-1]):
        if g["win"] == streak_result:
            streak += 1
        else:
            break
    trend = "up" if recent_avg > season_avg + 3 else ("down" if recent_avg < season_avg - 3 else "steady")
    return {
        "record_last_n": f"{wins}-{len(recent)-wins}",
        "games_considered": len(recent),
        "season_avg": season_avg,
        "recent_avg": recent_avg,
        "streak": streak,
        "streak_type": "W" if streak_result else "L",
        "trend": trend,
    }


def _players_to_watch(m, limit=4):
    pool = []
    for side in (m["home"], m["away"]):
        for s in side["starters"]:
            pool.append({**s, "owner": side["owner"]})
    pool.sort(key=lambda s: -s["proj"])
    return pool[:limit]


def _positional_edges(m):
    edges = []
    h_pos, a_pos = {}, {}
    for s in m["home"]["starters"]:
        h_pos[s["pos"]] = h_pos.get(s["pos"], 0.0) + s["proj"]
    for s in m["away"]["starters"]:
        a_pos[s["pos"]] = a_pos.get(s["pos"], 0.0) + s["proj"]
    for pos in sorted(set(h_pos) | set(a_pos)):
        hp, ap = round(h_pos.get(pos, 0.0), 1), round(a_pos.get(pos, 0.0), 1)
        diff = round(hp - ap, 1)
        edge = "home" if diff > 1 else ("away" if diff < -1 else "even")
        edges.append({"pos": pos, "home_proj": hp, "away_proj": ap, "edge": edge})
    return edges


def _revenge(team_games, home_id, away_id, before_week):
    for g in team_games.get(home_id, []):
        if g["week"] < before_week and g.get("opp") == away_id:
            return {"week": g["week"], "home_won": g["win"],
                    "home_pts": g["pts"], "away_pts": g["opp_pts"]}
    return None


def _ordinal(n):
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{'st' if n % 10 == 1 else 'nd' if n % 10 == 2 else 'rd' if n % 10 == 3 else 'th'}"


def _current_streak(team_games, team_id, before_week):
    hist = [g for g in team_games.get(team_id, []) if g["week"] < before_week]
    if not hist:
        return 0, None
    result = hist[-1]["win"]
    streak = 1
    for g in reversed(hist[:-1]):
        if g["win"] == result:
            streak += 1
        else:
            break
    return streak, ("W" if result else "L")


def _fun_facts(m, team_games, teams, before_week):
    facts = []
    h, a = m["home"], m["away"]
    h_hist = [g for g in team_games.get(h["teamId"], []) if g["week"] < before_week]
    a_hist = [g for g in team_games.get(a["teamId"], []) if g["week"] < before_week]

    meetings = sum(1 for g in team_games.get(h["teamId"], [])
                   if g["week"] < before_week and g.get("opp") == a["teamId"])
    if meetings >= 1:
        facts.append(f"This is their {_ordinal(meetings + 1)} meeting this season.")

    for side, hist in ((h, h_hist), (a, a_hist)):
        if not hist:
            continue
        hi, lo = max(g["pts"] for g in hist), min(g["pts"] for g in hist)
        if side["projected"] > hi:
            facts.append(f"If the projection holds, this would be {side['owner']}'s best week of the season.")
        elif side["projected"] < lo:
            facts.append(f"If the projection holds, this would be {side['owner']}'s worst week of the season.")

    best_len, best_owner = 0, None
    for tid, t in teams.items():
        length, typ = _current_streak(team_games, tid, before_week)
        if typ == "W" and length > best_len:
            best_len, best_owner = length, t["owner"]
    if best_len >= 2 and best_owner in (h["owner"], a["owner"]):
        facts.append(f"{best_owner} owns the league's longest active winning streak at {best_len} games.")

    return facts[:3]


def _full_roster(team_obj, scoring_period):
    """Every rostered player (starters + bench + IR) for a team, current lineup."""
    entries = team_obj.get("roster", {}).get("entries", [])
    slot_rank = {s: i for i, s in enumerate(
        [0, 2, 2, 4, 4, 6, 23, 16, 17, 20, 20, 20, 20, 20, 20, 21])}  # rough starter-first ordering
    players = []
    for e in entries:
        slot = e.get("lineupSlotId")
        pl = e.get("playerPoolEntry", {}).get("player", {})
        proj, act = _proj_and_actual(e, scoring_period)
        total, ppg, gp = season_stats_from_player(pl.get("stats", []), scoring_period)
        players.append({
            "player_id": pl.get("id"),
            "name": pl.get("fullName", "?"), "slot": SLOT.get(slot, str(slot)),
            "pos": POS.get(pl.get("defaultPositionId"), "?"),
            "pro": PRO.get(pl.get("proTeamId"), "?"),
            "proj": proj, "actual": act,
            "season_ppg": ppg, "season_total": total, "games_played": gp,
            "preseason_proj_total": preseason_projection(pl.get("stats", [])),
            "starter": slot in STARTER_SLOTS,
            "injury": pl.get("injuryStatus") if pl.get("injuryStatus") not in HEALTHY else None,
            "_rank": slot_rank.get(slot, 99),
        })
    players.sort(key=lambda p: (p["_rank"], -p["proj"]))
    for p in players:
        del p["_rank"]
    return players


def build_all_weeks(season):
    d = espn(["mTeam", "mSettings", "mMatchupScore", "mRoster", "mScoreboard"], season)
    if not d:
        return None
    members = d.get("members", [])
    status = d.get("status", {})
    cur_week = status.get("currentMatchupPeriod", 1)

    teams = {}
    for t in d.get("teams", []):
        name = (t.get("name") or f'{t.get("location","")} {t.get("nickname","")}').strip()
        rec = t.get("record", {}).get("overall", {})
        guid = t.get("primaryOwner") or (t.get("owners") or [None])[0]
        teams[t["id"]] = {
            "team_id": t["id"],
            "name": name, "guid": guid,
            "owner": _owner_name(members, guid) if guid else name,
            "record": f'{rec.get("wins",0)}-{rec.get("losses",0)}'
                      + (f'-{rec["ties"]}' if rec.get("ties") else ""),
            "pf": round(rec.get("pointsFor", 0.0), 1),
            "pa": round(rec.get("pointsAgainst", 0.0), 1),
            "waiver_rank": t.get("waiverRank"),
            "roster": _full_roster(t, status.get("currentMatchupPeriod", 1)),
        }

    # sort schedule by week so team_games accumulates chronologically
    schedule = sorted(
        (s for s in d.get("schedule", []) if "home" in s and "away" in s),
        key=lambda s: s.get("matchupPeriodId", 0),
    )

    team_games = {}  # teamId -> [{week, pts, win, opp, opp_pts}] chronological, played games only

    by_week = {}
    for s in schedule:
        wk = s.get("matchupPeriodId")
        h = _side(s["home"], teams, wk)
        a = _side(s["away"], teams, wk)
        played = (h["actual"] > 0 or a["actual"] > 0)
        phase = "recap" if played else "preview"
        is_playoff = s.get("playoffTierType", "NONE") != "NONE"
        m = {
            "home": h, "away": a, "played": played,
            "playoff": is_playoff,
            "margin": round(abs(h["actual"] - a["actual"]), 1) if played else None,
            "winner": (h["owner"] if h["actual"] > a["actual"] else a["owner"]) if played else None,
            "phase": phase,
        }
        m["blurb"] = _blurb(m, phase)
        if phase == "preview":
            m["home_form"] = _team_form(team_games, h["teamId"], wk)
            m["away_form"] = _team_form(team_games, a["teamId"], wk)
            m["players_to_watch"] = _players_to_watch(m)
            m["positional_edges"] = _positional_edges(m)
            m["revenge"] = _revenge(team_games, h["teamId"], a["teamId"], wk)
            m["fun_facts"] = _fun_facts(m, team_games, teams, wk)
        by_week.setdefault(wk, []).append(m)

        if played:
            team_games.setdefault(h["teamId"], []).append(
                {"week": wk, "pts": h["actual"], "win": h["actual"] > a["actual"],
                 "opp": a["teamId"], "opp_pts": a["actual"]})
            team_games.setdefault(a["teamId"], []).append(
                {"week": wk, "pts": a["actual"], "win": a["actual"] > h["actual"],
                 "opp": h["teamId"], "opp_pts": h["actual"]})

    standings_order = sorted(teams.keys(),
                              key=lambda tid: (-_wins(teams[tid]["record"]), -teams[tid]["pf"]))
    standings = [teams[tid] for tid in standings_order]
    return {
        "season": season, "current_week": cur_week,
        "standings": standings, "weeks": by_week,
    }


def _wins(rec):
    try:
        return int(rec.split("-")[0])
    except Exception:
        return 0
