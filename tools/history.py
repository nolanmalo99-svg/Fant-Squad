"""Pull every season 2022->present from ESPN and compute career stats, head-to-head,
season-by-season records, champions, and league records -- all derived live, nothing
hand-typed. Owners are tracked by their stable ESPN member GUID so a name change or a
team-name change never breaks career totals.
"""
from lib import espn, FIRST_SEASON


def _owner_name(members, guid):
    for m in members:
        if m.get("id") == guid:
            fn, ln = (m.get("firstName") or "").strip(), (m.get("lastName") or "").strip()
            return f"{fn} {ln}".strip() or m.get("displayName", guid)
    return guid


def _season_snapshot(season):
    """One ESPN call -> teams, members, full schedule w/ scores for that season."""
    d = espn(["mTeam", "mSettings", "mMatchupScore"], season)
    if not d or not d.get("teams"):
        return None
    members = d.get("members", [])
    teams = {}
    for t in d["teams"]:
        guid = t.get("primaryOwner") or (t.get("owners") or [None])[0]
        name = (t.get("name") or f'{t.get("location","")} {t.get("nickname","")}').strip()
        rec = t.get("record", {}).get("overall", {})
        teams[t["id"]] = {
            "guid": guid,
            "owner": _owner_name(members, guid) if guid else name,
            "team": name,
            "wins": rec.get("wins", 0), "losses": rec.get("losses", 0),
            "ties": rec.get("ties", 0),
            "pf": round(rec.get("pointsFor", 0.0), 1),
            "pa": round(rec.get("pointsAgainst", 0.0), 1),
            "final_rank": t.get("rankCalculatedFinal") or 0,
        }
    status = d.get("status", {})
    settings = d.get("settings", {}).get("scheduleSettings", {})
    reg_season_len = settings.get("matchupPeriodCount", 14)
    playoff_started_period = reg_season_len  # last regular-season matchup period
    finished = status.get("currentMatchupPeriod", 0) > reg_season_len \
        and status.get("standingsUpdateDate") is not None
    games = []
    for s in d.get("schedule", []):
        if "home" not in s or "away" not in s:
            continue
        h, a = s["home"], s["away"]
        hp, ap = h.get("totalPoints", 0.0), a.get("totalPoints", 0.0)
        if hp == 0 and ap == 0:
            continue  # not played
        games.append({
            "week": s.get("matchupPeriodId"),
            "playoff": s.get("playoffTierType", "NONE") != "NONE",
            "home_id": h["teamId"], "away_id": a["teamId"],
            "home_pts": round(hp, 1), "away_pts": round(ap, 1),
        })
    return {"season": season, "teams": teams, "games": games, "finished": finished}


def build_history(current_season):
    seasons = []
    s = FIRST_SEASON
    while s <= current_season:
        snap = _season_snapshot(s)
        if snap:
            seasons.append(snap)
        s += 1
    if not seasons:
        return None

    career = {}  # guid -> stats

    def cget(guid, owner):
        if guid not in career:
            career[guid] = {
                "owner": owner, "team": "", "w": 0, "l": 0, "t": 0, "pf": 0.0,
                "seasons": [], "best_week": None, "h2h": {}, "playoff_wins": 0,
                "playoff_appearances": set(), "winning_seasons": 0,
            }
        career[guid]["owner"] = owner  # keep most-recent display name
        return career[guid]

    champions_timeline = []
    last_place_timeline = []

    for snap in seasons:
        season, teams, games, finished = snap["season"], snap["teams"], snap["games"], snap["finished"]

        # per-owner season line + career totals
        for t in teams.values():
            c = cget(t["guid"], t["owner"])
            c["team"] = t["team"]
            c["w"] += t["wins"]; c["l"] += t["losses"]; c["t"] += t["ties"]
            c["pf"] += t["pf"]
            if t["wins"] > t["losses"]:
                c["winning_seasons"] += 1
            c["seasons"].append({
                "season": season, "team": t["team"],
                "record": f'{t["wins"]}-{t["losses"]}' + (f'-{t["ties"]}' if t["ties"] else ""),
                "pf": t["pf"],
            })

        # champion / last place (only for seasons ESPN has finalized rankings for)
        ranked = [t for t in teams.values() if t["final_rank"]]
        if finished and ranked:
            champ = min(ranked, key=lambda t: t["final_rank"])
            last = max(ranked, key=lambda t: t["final_rank"])
            champions_timeline.append({
                "season": season, "owner": champ["owner"], "team": champ["team"],
                "record": f'{champ["wins"]}-{champ["losses"]}', "pf": champ["pf"],
            })
            last_place_timeline.append({
                "season": season, "owner": last["owner"], "team": last["team"],
                "record": f'{last["wins"]}-{last["losses"]}', "pf": last["pf"],
            })

        # games -> best week, blowouts, head-to-head, playoff tallies
        for g in games:
            ht, at = teams.get(g["home_id"]), teams.get(g["away_id"])
            if not ht or not at:
                continue
            for side_owner, pts in ((ht, g["home_pts"]), (at, g["away_pts"])):
                c = cget(side_owner["guid"], side_owner["owner"])
                if pts and (c["best_week"] is None or pts > c["best_week"]["points"]):
                    c["best_week"] = {"points": pts, "week": g["week"], "season": season}

            h_win = g["home_pts"] > g["away_pts"]
            winner, loser = (ht, at) if h_win else (at, ht)
            wc, lc = cget(winner["guid"], winner["owner"]), cget(loser["guid"], loser["owner"])
            wc["h2h"].setdefault(loser["guid"], {"owner": loser["owner"], "guid": loser["guid"], "w": 0, "l": 0})
            lc["h2h"].setdefault(winner["guid"], {"owner": winner["owner"], "guid": winner["guid"], "w": 0, "l": 0})
            wc["h2h"][loser["guid"]]["owner"] = loser["owner"]
            lc["h2h"][winner["guid"]]["owner"] = winner["owner"]
            wc["h2h"][loser["guid"]]["w"] += 1
            lc["h2h"][winner["guid"]]["l"] += 1
            if g["playoff"]:
                wc["playoff_wins"] += 1
                wc["playoff_appearances"].add(season)
                lc["playoff_appearances"].add(season)

    # league-wide records
    best_week = None
    biggest_blowout = None
    for snap in seasons:
        teams = snap["teams"]
        for g in snap["games"]:
            ht, at = teams.get(g["home_id"]), teams.get(g["away_id"])
            if not ht or not at:
                continue
            for side, pts in ((ht, g["home_pts"]), (at, g["away_pts"])):
                if best_week is None or pts > best_week["points"]:
                    best_week = {"points": pts, "owner": side["owner"], "team": side["team"],
                                 "week": g["week"], "season": snap["season"]}
            margin = round(abs(g["home_pts"] - g["away_pts"]), 1)
            if biggest_blowout is None or margin > biggest_blowout["margin"]:
                winner, loser = (ht, at) if g["home_pts"] > g["away_pts"] else (at, ht)
                wp = g["home_pts"] if g["home_pts"] > g["away_pts"] else g["away_pts"]
                lp = g["away_pts"] if g["home_pts"] > g["away_pts"] else g["home_pts"]
                biggest_blowout = {"margin": margin, "winner": winner["owner"], "loser": loser["owner"],
                                    "winner_pts": wp, "loser_pts": lp,
                                    "week": g["week"], "season": snap["season"]}

    for c in career.values():
        c["playoff_appearances"] = len(c["playoff_appearances"])
        c["h2h"] = list(c["h2h"].values())

    most_wins = max(career.values(), key=lambda c: c["w"]) if career else None
    most_pf = max(career.values(), key=lambda c: c["pf"]) if career else None

    return {
        "seasons_covered": [s["season"] for s in seasons],
        "current_season_finished": seasons[-1]["finished"] if seasons else False,
        "career": career,
        "champions_timeline": champions_timeline,
        "last_place_timeline": last_place_timeline,
        "records": {
            "best_week": best_week,
            "biggest_blowout": biggest_blowout,
            "most_career_wins": ({"owner": most_wins["owner"], "w": most_wins["w"], "l": most_wins["l"]}
                                  if most_wins else None),
            "most_career_pf": ({"owner": most_pf["owner"], "pf": round(most_pf["pf"], 1)}
                                if most_pf else None),
        },
    }
