#!/usr/bin/env python3
"""Regenerate the whole site's data from the ESPN API. Run manually or via GitHub Action.

  python3 tools/build_data.py                # auto-detect current season
  python3 tools/build_data.py --season 2026
"""
import argparse, datetime, json, sys
from lib import ROOT, load_env, FIRST_SEASON, espn
import league as L
import history as H
import draft as D

LEAGUE_NAME = "Fant Squad"


def detect_current_season():
    guess = datetime.date.today().year
    for season in (guess, guess - 1):
        d = espn(["mSettings"], season)
        if d:
            return season
    return FIRST_SEASON


def _write_js(path, var_name, data):
    path.write_text(f"window.{var_name} = " + json.dumps(data, indent=2) + ";\n")


def _attach_head_to_head(weeks, career):
    """Career (multi-season) head-to-head, keyed by owner GUID, attached to preview matchups."""
    for games in weeks.values():
        for m in games:
            if m.get("phase") != "preview":
                continue
            h_guid, a_guid = m["home"].get("guid"), m["away"].get("guid")
            h2h = None
            for entry in career.get(h_guid, {}).get("h2h", []):
                if entry.get("guid") == a_guid:
                    h2h = {"home_w": entry["w"], "home_l": entry["l"]}
                    break
            m["head_to_head"] = h2h


def run(season=None):
    load_env()
    season = season or detect_current_season()
    print(f"season: {season}")

    week_data = L.build_all_weeks(season)
    if week_data is None:
        sys.exit(f"no ESPN data for season {season} -- check LEAGUE_ID / cookies")

    try:
        hist = H.build_history(season)
    except Exception as e:
        print(f"[history] build_history failed, continuing without it for this run: {e}")
        hist = None

    champions_timeline = hist["champions_timeline"] if hist else []
    last_place_timeline = hist["last_place_timeline"] if hist else []
    reigning_champion = champions_timeline[-1] if champions_timeline else None
    reigning_last_place = last_place_timeline[-1] if last_place_timeline else None

    career_out = {}
    roster_by_guid = {t["guid"]: t.get("roster", []) for t in week_data["standings"]}
    if hist:
        for guid, c in hist["career"].items():
            wins, losses = c["w"], c["l"]
            gp = wins + losses + c["t"]
            career_out[guid] = {
                "owner": c["owner"], "team": c["team"],
                "record": f'{wins}-{losses}' + (f'-{c["t"]}' if c["t"] else ""),
                "pf": round(c["pf"], 1),
                "win_pct": round(100 * wins / gp) if gp else 0,
                "seasons": sorted(c["seasons"], key=lambda s: s["season"]),
                "best_week": c["best_week"],
                "h2h": sorted(c["h2h"], key=lambda x: x["owner"]),
                "playoff_wins": c["playoff_wins"],
                "playoff_appearances": c["playoff_appearances"],
                "winning_seasons": c["winning_seasons"],
                "roster": roster_by_guid.get(guid, []),
            }

    with_waiver = [t for t in week_data["standings"] if t.get("waiver_rank")]
    waiver_order = sorted(
        [{"owner": t["owner"], "team": t["name"], "waiver_rank": t["waiver_rank"]} for t in with_waiver],
        key=lambda t: t["waiver_rank"],
    )

    draft_grades = None
    try:
        draft_grades = D.build_draft_grades(season, week_data["standings"], week_data["current_week"])
        print(f"[draft] build_draft_grades returned: {'None' if draft_grades is None else len(draft_grades)} teams")
        if draft_grades:
            matched = set(draft_grades) & set(career_out)
            print(f"[draft] draft guids: {len(draft_grades)}, career_out guids: {len(career_out)}, "
                  f"matched: {len(matched)}, hist_present: {hist is not None}")
        if draft_grades and hist:
            for guid, dg in draft_grades.items():
                if guid in career_out:
                    career_out[guid]["draft"] = dg
    except Exception as e:
        print(f"[draft] current-season draft grading failed, skipping for this run: {e}")

    # Draft history: every past completed season's grade, so owners can see year-by-year drafts.
    # Wrapped defensively: this makes many ESPN calls, and a network blip here should never cost
    # us the standings/history/awards/matchups data that already succeeded above.
    historical_draft = {}
    try:
        historical_draft = D.build_historical_draft_grades(FIRST_SEASON, season - 1)
        print(f"[draft] historical seasons graded: {sorted(historical_draft.keys())}")
    except Exception as e:
        print(f"[draft] historical draft grading failed, skipping for this run: {e}")

    draft_history_by_guid = {}
    for hist_season, season_results in historical_draft.items():
        for guid, dg in season_results.items():
            entry = dict(dg)
            entry["season"] = hist_season
            draft_history_by_guid.setdefault(guid, []).append(entry)
    if draft_grades:
        for guid, dg in draft_grades.items():
            entry = dict(dg)
            entry["season"] = season
            draft_history_by_guid.setdefault(guid, []).append(entry)
    for guid, timeline in draft_history_by_guid.items():
        if guid in career_out:
            career_out[guid]["draft_history"] = sorted(timeline, key=lambda x: x["season"])

    site_data = {
        "league_name": LEAGUE_NAME,
        "first_season": FIRST_SEASON,
        "current_season": season,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "current_week": week_data["current_week"],
        "standings": [{k: v for k, v in t.items() if k != "roster"} for t in week_data["standings"]],
        "waiver_order": waiver_order,
        "reigning_champion": reigning_champion,
        "reigning_last_place": reigning_last_place,
        "champions_timeline": champions_timeline,
        "last_place_timeline": last_place_timeline,
        "career": career_out,
        "records": hist["records"] if hist else {},
        "seasons_covered": hist["seasons_covered"] if hist else [season],
    }

    matchups_data = {
        "season": season,
        "current_week": week_data["current_week"],
        "weeks": week_data["weeks"],
    }
    if hist:
        _attach_head_to_head(matchups_data["weeks"], hist["career"])

    js_dir = ROOT / "js"
    js_dir.mkdir(exist_ok=True)
    _write_js(js_dir / "site-data.js", "SITE_DATA", site_data)
    _write_js(js_dir / "matchups-data.js", "MATCHUPS_DATA", matchups_data)

    data_dir = ROOT / "tools" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"{season}-latest.json").write_text(json.dumps(site_data, indent=2))

    print(f"wrote js/site-data.js, js/matchups-data.js "
          f"({len(site_data['standings'])} teams, {len(matchups_data['weeks'])} weeks)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    a = ap.parse_args()
    run(a.season)
