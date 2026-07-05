#!/usr/bin/env python3
"""Job-finder daily refresh merger.

Usage:
    python3 refresh.py                # merge found-jobs.json (+ optional found-companies.json) into data.js
    python3 refresh.py --push         # same, then commit data.js and push to GitHub (updates the live site)

Reads, from this script's own directory:
    data.js              existing dataset (window.JF_DATA = {...};)
    found-jobs.json      today's research results: array of
                         {title, company, location, workModel, url, postedDate, seniority, whyFit}
    found-companies.json optional: array of
                         {name, category, location, careersUrl, linkedinUrl, size, workCulture, notes}

Writes:
    data.js              merged dataset, meta.lastUpdated = today
    summary.json         digest for the daily email: {date, newJobs[], staleJobs[], removedJobs[], counts{}}

Merge rules:
    - job id = slug(company + title); stable across runs so localStorage state sticks.
    - job seen today  -> lastSeen = today (firstSeen preserved)
    - job not seen    -> kept, lastSeen unchanged (UI flags "recheck")
    - job unseen 30d+ -> dropped (listed in summary.removedJobs)
    - companies merged by slug(name); existing entries win, new ones appended.
"""
import json, re, subprocess, sys, unicodedata
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODAY = date.today().isoformat()
STALE_DROP_DAYS = 30

IL_HINTS = ("israel", "tel aviv", "tel-aviv", "herzliya", "ramat gan", "ramat-gan",
            "netanya", "haifa", "jerusalem", "givatayim", "petah", "bnei brak",
            "raanana", "ra'anana", "rehovot", "or yehuda", "holon", "rishon")


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80] or "x"


def is_israel(job: dict) -> bool:
    loc = (job.get("location") or "").lower()
    # "Remote — Istanbul, same TZ as Tel Aviv" must not count as Israel:
    # a leading "remote" means Israel only if named explicitly.
    if loc.startswith("remote") and "israel" not in loc:
        return False
    return any(h in loc for h in IL_HINTS)


def tier(job: dict) -> int:
    model = (job.get("workModel") or "unknown").lower()
    if is_israel(job):
        if "hybrid" in model:
            return 1
        if "remote" in model:
            return 2
        return 3  # onsite / unknown -> office tier until verified
    return 4


def load_existing() -> dict:
    txt = (HERE / "data.js").read_text(encoding="utf-8")
    m = re.search(r"window\.JF_DATA\s*=\s*(\{.*\})\s*;?\s*$", txt, re.S)
    if not m:
        print("ERROR: could not parse data.js", file=sys.stderr)
        sys.exit(1)
    return json.loads(m.group(1))


def norm_url(u: str) -> str:
    # keep query strings — Greenhouse/Comeet boards distinguish jobs only by ?gh_jid=/?uid=
    return (u or "").replace("https://il.linkedin.com", "https://www.linkedin.com").rstrip("/").lower()


def culture_fallback(job: dict, companies: dict) -> str:
    """When a posting doesn't state a work model, fall back to the company's known culture."""
    jslug = slug(job.get("company", ""))
    for c in companies.values():
        cslug = slug(c.get("name", ""))
        if cslug.startswith(jslug) or jslug.startswith(cslug):
            culture = (c.get("workCulture") or "").lower()
            if culture == "hybrid":
                return "hybrid"
            if culture == "office":
                return "onsite"
    return "unknown"


def main() -> None:
    data = load_existing()
    old_jobs = {j["id"]: j for j in data.get("jobs", [])}
    old_urls = {norm_url(j.get("url")): j["id"] for j in old_jobs.values()}

    # companies first, so unknown work models can inherit the company's culture
    companies = {c["id"]: c for c in data.get("companies", [])}
    cpath = HERE / "found-companies.json"
    if cpath.exists():
        for c in json.loads(cpath.read_text(encoding="utf-8")):
            if not c.get("name"):
                continue
            cid = slug(c["name"])
            if cid not in companies:
                companies[cid] = {
                    "id": cid,
                    "name": c["name"].strip(),
                    "category": c.get("category") or "il-gaming",
                    "location": (c.get("location") or "").strip(),
                    "careersUrl": (c.get("careersUrl") or "").strip(),
                    "linkedinUrl": (c.get("linkedinUrl") or "").strip(),
                    "size": (c.get("size") or "").strip(),
                    "workCulture": (c.get("workCulture") or "unknown").strip(),
                    "notes": (c.get("notes") or "").strip(),
                }

    found_path = HERE / "found-jobs.json"
    if not found_path.exists():
        print("ERROR: found-jobs.json missing — research step must write it first", file=sys.stderr)
        sys.exit(1)
    found = json.loads(found_path.read_text(encoding="utf-8"))

    new_jobs, seen_ids = [], set()
    for f in found:
        if not f.get("url") or not f.get("title") or not f.get("company"):
            continue
        jid = old_urls.get(norm_url(f["url"])) or slug(f["company"] + "-" + f["title"])
        if jid in seen_ids:
            continue
        seen_ids.add(jid)
        prev = old_jobs.get(jid)
        job = {
            "id": jid,
            "title": f["title"].strip(),
            "company": f["company"].strip(),
            "location": (f.get("location") or "").strip(),
            "workModel": (f.get("workModel") or "unknown").strip().lower(),
            "url": f["url"].strip(),
            "companyUrl": (f.get("companyUrl") or (prev or {}).get("companyUrl") or "").strip(),
            "postedDate": (f.get("postedDate") or (prev or {}).get("postedDate") or "").strip(),
            "seniority": (f.get("seniority") or "").strip(),
            "whyFit": (f.get("whyFit") or "").strip(),
            "firstSeen": (prev or {}).get("firstSeen") or TODAY,
            "lastSeen": TODAY,
        }
        if job["workModel"] in ("", "unknown"):
            job["workModel"] = culture_fallback(job, companies)
        job["tier"] = tier(job)
        old_jobs[jid] = job
        if not prev:
            new_jobs.append(job)

    # age-out: drop long-unseen jobs
    removed, kept = [], []
    for j in old_jobs.values():
        unseen_days = (date.today() - datetime.strptime(j.get("lastSeen", TODAY), "%Y-%m-%d").date()).days
        (removed if unseen_days >= STALE_DROP_DAYS else kept).append(j)
    stale = [j for j in kept if j.get("lastSeen") != TODAY]

    kept.sort(key=lambda j: (j["tier"], j["firstSeen"]), reverse=False)
    out = {
        "meta": {"lastUpdated": TODAY, "refreshNote": f"{len(new_jobs)} new / {len(kept)} total"},
        "jobs": kept,
        "companies": sorted(companies.values(), key=lambda c: (c["category"], c["name"])),
    }
    (HERE / "data.js").write_text(
        "/* Auto-generated by the daily job-finder refresh. Do not edit by hand —\n"
        "   your personal statuses/notes live in localStorage, not here. */\n"
        "window.JF_DATA = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )

    counts = {f"tier{t}": sum(1 for j in kept if j["tier"] == t) for t in (1, 2, 3, 4)}
    counts["total"] = len(kept)
    summary = {
        "date": TODAY,
        "counts": counts,
        "newJobs": new_jobs,
        "staleJobs": [{"id": j["id"], "title": j["title"], "company": j["company"], "lastSeen": j["lastSeen"]} for j in stale],
        "removedJobs": [{"title": j["title"], "company": j["company"]} for j in removed],
    }
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    pushed = False
    if "--push" in sys.argv:
        try:
            subprocess.run(["git", "-C", str(HERE), "add", "data.js"], check=True, capture_output=True)
            diff = subprocess.run(["git", "-C", str(HERE), "diff", "--cached", "--quiet"])
            if diff.returncode != 0:  # staged changes exist
                subprocess.run(["git", "-C", str(HERE), "-c", "user.name=amotzalbert",
                                "-c", "user.email=amotzalbert@gmail.com",
                                "commit", "-m", f"Daily refresh {TODAY}: {len(new_jobs)} new / {len(kept)} total"],
                               check=True, capture_output=True)
                subprocess.run(["git", "-C", str(HERE), "push"], check=True, capture_output=True, timeout=120)
                pushed = True
        except Exception as e:  # never let publish failure kill the merge result
            print(f"WARNING: git push failed: {e}", file=sys.stderr)

    print(json.dumps({"ok": True, **counts, "new": len(new_jobs), "stale": len(stale),
                      "removed": len(removed), "pushed": pushed}))


if __name__ == "__main__":
    main()
