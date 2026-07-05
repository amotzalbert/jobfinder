# Amotz // Job Finder

Personal job-search dashboard for gaming / creative-AI leadership roles.

**Live site:** https://amotzalbert.github.io/jobfinder/ (repo: `amotzalbert/jobfinder`)
**Local:** double-click `index.html` (works from `file://`, no server needed).

Note: statuses/notes are per-browser (localStorage) — the online site and the local file each keep their own; use Backup/Restore to move state between them.

## Priorities (baked into the tier system)
1. 🥇 Israel Hybrid
2. 🥈 Israel Remote
3. 🥉 Israel 5-days office
4. 🌍 Remote International

## Files
| File | What it is |
|---|---|
| `index.html` | The dashboard (single file, vanilla JS) |
| `data.js` | Auto-generated dataset — **never edit by hand** |
| `refresh.py` | Merge engine used by the daily refresh |
| `found-jobs.json` | Scratch: today's research results (input to refresh.py) |
| `summary.json` | Scratch: digest used for the daily email |

## Daily refresh (scheduled task `job-finder-daily-refresh`)
Every day at **08:30**, a scheduled Claude task:
1. Re-searches all sources for openings matching the profile
2. Writes `found-jobs.json`, then runs `python3 refresh.py --push` (stable IDs, firstSeen/lastSeen, 30-day age-out; commits & pushes `data.js` so the live site updates)
3. Emails a daily summary via Zapier Gmail

Runs only while the Claude desktop app is open; if it was closed at 08:30, it fires on next launch.

## Your data
Statuses, stars, notes (jobs + companies) are stored in **localStorage of the browser** you open the file with — the daily refresh never touches them. Use **⬇ Backup / ⬆ Restore** in the header to move them between browsers/machines.

Badge logic: **NEW** = first seen in the latest refresh · **⚠ recheck** = listing wasn't found in the latest refresh (may be closed; auto-removed after 30 days unseen unless still in your pipeline).
