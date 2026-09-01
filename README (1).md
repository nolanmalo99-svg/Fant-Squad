# Fant Squad — Fantasy Football League Site

A static site for your ESPN fantasy league. Every page (standings, teams, history, awards,
matchups, trade analyzer) is rendered in the browser from JSON pulled live out of the ESPN
Fantasy API — nothing is hand-typed. A GitHub Action re-syncs that data on a schedule and
commits it, so GitHub Pages always shows a recent snapshot.

Your League ID (`1090125`) is already baked into `tools/lib.py` — it's not sensitive, it's
just the public ID in your league's URL. What *is* sensitive is your ESPN login cookies,
which are required because your league is private.

## 1. Get your ESPN cookies

1. Log into your league at https://fantasy.espn.com in a desktop browser.
2. Open DevTools (F12) → **Application** (Chrome) or **Storage** (Firefox) → **Cookies** →
   `https://fantasy.espn.com`.
3. Copy the values of two cookies:
   - `espn_s2` (a long string)
   - `SWID` (looks like `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`, including the curly braces)

## 2. Add them as GitHub Secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `ESPN_S2` | the `espn_s2` cookie value |
| `ESPN_SWID` | the `SWID` cookie value (with braces) |

## 3. Turn on GitHub Pages

**Settings → Pages → Source: Deploy from a branch → `main` / `/(root)`**. Your site will be
live at `https://<you>.github.io/<repo>/`.

## 4. Run the first sync

Go to **Actions → Sync ESPN data → Run workflow**. This fetches every season since 2015,
computes standings/history/awards/head-to-head/draft grades, and commits `js/site-data.js` +
`js/matchups-data.js`. Refresh the site after it finishes.

After that, it re-runs automatically on a schedule during the season — every 15 minutes during
Sunday/Thursday/Monday NFL windows, every 4 hours otherwise. You can always trigger it manually
from the Actions tab too.

## Running locally (optional)

```bash
cd tools
echo "ESPN_S2=..."   >> .env
echo "ESPN_SWID=..." >> .env
python3 build_data.py
```

This writes `js/site-data.js` and `js/matchups-data.js` in the project root — open
`home.html` directly in a browser (or `python3 -m http.server` from the project root) to
preview.

## Project layout

```
home.html, teams.html, history.html, awards.html, matchups.html, trade-analyzer.html -- static page shells
js/site-data.js, js/matchups-data.js                               -- GENERATED, don't hand-edit
js/gate.js, js/polish.js                                            -- site chrome, generic
css/style.css                                                       -- theme (blue/white/silver/black)
tools/lib.py       -- ESPN API client + league ID + position/team constants
tools/league.py    -- pulls this season's matchups/rosters/scores (one API call)
tools/history.py   -- pulls every season, computes career stats/h2h/records
tools/draft.py     -- grades each team's draft vs. actual/projected production
tools/build_data.py -- orchestrates the above, writes the js/*.js data files
.github/workflows/sync.yml -- scheduled + manual sync job
```
