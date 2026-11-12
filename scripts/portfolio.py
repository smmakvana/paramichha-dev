#!/usr/bin/env python3
"""One page for all repositories: how healthy is each one's latest build, and the totals.

Reads, per repository named in the config, what the overview workflow collected:
  <data>/<repo>/run.json       the latest completed build on master (conclusion, createdAt, url, ...)
  <data>/<repo>/summary.json   optional: report-summary.py's numbers from that build
and writes <out>/index.html, <out>/overview.json and, when GITHUB_STEP_SUMMARY is set, a Markdown table.

Only public repositories belong in the config: the page can be published openly.
Best effort like report-summary.py: any problem prints a warning and exits 0.
Standard library only. Usage: portfolio.py --data data --config scripts/portfolio.json --out overview
"""
import argparse
import datetime
import html
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("report_summary", os.path.join(HERE, "report-summary.py"))
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)  # reuse the single-build page's look: CSS, escaping, tables, plural

LOW_BRANCH = 90.0


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def parse_time(text):
    try:
        return datetime.datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def ago(then, now):
    if then is None:
        return "never"
    days = (now - then).days
    if days >= 1:
        return rs.plural(days, "day") + " ago"
    hours = (now - then).seconds // 3600
    return rs.plural(hours, "hour") + " ago" if hours else "just now"


def collect(data_dir, config, now):
    owner, stale_days = config.get("owner", ""), config.get("stale_days", 14)
    repos = []
    for entry in config["repos"]:
        name = entry["name"]
        run = load(os.path.join(data_dir, name, "run.json")) or {}
        summary = load(os.path.join(data_dir, name, "summary.json"))
        built = parse_time(run.get("createdAt"))
        stale = built is not None and (now - built).days > stale_days
        conclusion = run.get("conclusion") or ""
        if not run:
            status, level = "No build", "none"
        elif conclusion != "success":
            status, level = "Failing", "bad"
        elif summary and summary["meta"]["verdict"] != "Passing":
            status, level = summary["meta"]["verdict"], "bad" if summary["meta"]["verdict"] == "Failing" else "warn"
        elif stale:
            status, level = "Stale", "warn"
        else:
            status, level = "Passing", "good"
        row = {"name": name, "about": entry.get("about", ""), "status": status, "level": level,
               "url": f"https://github.com/{owner}/{name}" if owner else "", "run_url": run.get("url", ""),
               "built": run.get("createdAt", ""), "built_ago": ago(built, now), "stale": stale,
               "commit": (run.get("headSha") or "")[:7], "has_report": bool(summary),
               "coverage_counts": entry.get("coverage", True), "coverage_note": entry.get("coverage_note", "")}
        if summary:
            t, c = summary.get("tests") or {}, summary.get("coverage") or {}
            row.update({"tests": t.get("run"), "tests_failed": t.get("failed", 0),
                        "lines": c.get("lines"), "lines_covered": c.get("lines_covered"),
                        "branches": c.get("branches"), "branches_covered": c.get("branches_covered"),
                        "line_pct": c.get("line_pct"), "branch_pct": c.get("branch_pct"),
                        "findings": summary["meta"].get("issues", 0),
                        "duplicated": (summary.get("duplication") or {}).get("count", 0)})
        repos.append(row)
    return repos


def pct_cell(r, key):
    """The figure for a table cell: a dash with no report, n/a where coverage is not counted."""
    if not r["has_report"]:
        return "–"
    return rs.fmt_pct(r.get(key)) if r["coverage_counts"] else "n/a"


def totals(repos):
    with_report = [r for r in repos if r["has_report"]]

    def total(key):
        return sum(r.get(key) or 0 for r in with_report)

    counted = [r for r in with_report if r["coverage_counts"]]  # sample classes etc. are left out of coverage

    def covered(key):
        return sum(r.get(key) or 0 for r in counted)

    lines, branches = covered("lines"), covered("branches")
    return {"repositories": len(repos), "passing": sum(r["level"] == "good" for r in repos),
            "tests": total("tests"), "tests_failed": total("tests_failed"),
            "line_pct": 100.0 * covered("lines_covered") / lines if lines else None,
            "branch_pct": 100.0 * covered("branches_covered") / branches if branches else None,
            "lines": lines, "lines_covered": covered("lines_covered"), "branches": branches, "branches_covered": covered("branches_covered"),
            "findings": total("findings"), "duplicated": total("duplicated"), "with_report": len(with_report)}


def attention(repos):
    """What a reader should look at first, most serious first."""
    items = []
    for r in repos:
        if r["level"] == "bad":
            items.append((0, f"{r['name']}: {r['status'].lower()}. Open its latest build."))
        elif r["status"] == "Stale":
            items.append((1, f"{r['name']}: the last build was {r['built_ago']}."))
        elif r["status"] == "No build":
            items.append((1, f"{r['name']}: no build was found."))
        elif r["level"] == "warn":
            items.append((1, f"{r['name']}: {r['status'].lower()}."))
    for r in sorted((r for r in repos if r["has_report"] and r["coverage_counts"] and r.get("branch_pct") is not None
                     and r["branch_pct"] < LOW_BRANCH),
                    key=lambda r: r["branch_pct"]):
        items.append((2, f"{r['name']}: branch coverage is {rs.fmt_pct(r['branch_pct'])}, below {LOW_BRANCH:.0f}%."))
    for r in repos:
        if r["has_report"] and r.get("duplicated"):
            items.append((3, f"{r['name']}: {rs.plural(r['duplicated'], 'duplicated block')}. Informational."))
    return [text for _, text in sorted(items, key=lambda i: i[0])]


def verdict(repos):
    if any(r["level"] == "bad" for r in repos):
        return "Failing", "bad"
    if any(r["level"] in ("warn", "none") for r in repos):
        return "Needs attention", "warn"
    return ("Passing", "good") if repos else ("No results", "none")


def headline(tot, repos, v):
    n = tot["repositories"]
    if v == "Passing":
        text = f"All {n} repositories build cleanly."
    else:
        bad = [r["name"] for r in repos if r["level"] != "good"]
        text = f"{tot['passing']} of {n} repositories are healthy; look at {', '.join(bad)}."
    if tot["with_report"]:
        text += f" {tot['tests']:,} tests ran"
        text += " and all pass." if not tot["tests_failed"] else f"; {tot['tests_failed']} failed."
    return text


def render(repos, tot, now):
    v, level = verdict(repos)
    head = headline(tot, repos, v)

    def card(label, number, sub, status, pct=None):
        icon, word = rs.STATUS[status]
        bar = f'<div class="bar"><i style="width:{max(0.0, min(100.0, pct)):.1f}%"></i></div>' if pct is not None else ""
        return (f'<div class="card {status}"><div class="l">{rs.esc(label)}</div><div class="n">{rs.esc(number)}</div>{bar}'
                f'<div class="s">{rs.esc(sub)}</div><div class="foot"><span class="st">{icon} {word}</span></div></div>')

    def pct_status(p):
        return "none" if p is None else "good" if p >= 90 else "warn" if p >= 75 else "bad"

    cards = [card("Repositories", f"{tot['passing']}/{tot['repositories']}", "with a healthy build", "good" if v == "Passing" else level)]
    if tot["with_report"]:
        cards += [card("Tests", f"{tot['tests']:,}", f"{tot['tests_failed']} failed" if tot["tests_failed"] else "all passing",
                       "bad" if tot["tests_failed"] else "good"),
                  card("Line coverage", rs.fmt_pct(tot["line_pct"]), f"{tot['lines_covered']:,} of {tot['lines']:,} lines", pct_status(tot["line_pct"]), tot["line_pct"]),
                  card("Branch coverage", rs.fmt_pct(tot["branch_pct"]), f"{tot['branches_covered']:,} of {tot['branches']:,} branches",
                       pct_status(tot["branch_pct"]), tot["branch_pct"]),
                  card("Findings", tot["findings"], "style, smells and bug patterns", "good" if not tot["findings"] else "bad"),
                  card("Duplicated code", tot["duplicated"], "blocks, informational", "good" if not tot["duplicated"] else "warn")]

    order = sorted(repos, key=lambda r: ({"bad": 0, "warn": 1, "none": 1, "good": 2}[r["level"]], r["name"]))
    rows = []
    for r in order:
        name = f'<a href="{rs.esc(r["url"])}">{rs.esc(r["name"])}</a>' if r["url"] else rs.esc(r["name"])
        when = rs.esc(r["built_ago"])
        if r["run_url"]:
            when = f'<a href="{rs.esc(r["run_url"])}">{when}</a>'
        tests = f"{r['tests']:,}" if r["has_report"] and r.get("tests") is not None else "–"
        findings = r.get("findings", "–") if r["has_report"] else "–"
        rows.append(f'<tr><td><strong>{name}</strong><br><span class="mute">{rs.esc(r["about"])}</span></td>'
                    f'<td><span class="pill {r["level"]}">{rs.esc(r["status"])}</span></td>'
                    f'<td class="num">{rs.esc(tests)}</td>'
                    f'<td class="num">{rs.esc(pct_cell(r, "line_pct"))}</td><td class="num">{rs.esc(pct_cell(r, "branch_pct"))}</td>'
                    f'<td class="num">{rs.esc(findings)}</td><td class="num">{when}</td></tr>')
    table = ('<div class="scroll"><table><tr><th>Repository</th><th>Latest build</th><th>Tests</th><th>Lines</th><th>Branches</th>'
             f'<th>Findings</th><th>Built</th></tr>{"".join(rows)}</table></div>')

    look = attention(repos)
    look_html = ("<h2>Worth a look</h2><ul>" + "".join(f"<li>{rs.esc(t)}</li>" for t in look) + "</ul>") if look else \
        "<h2>Worth a look</h2><p class=\"mute\">Nothing: every build is healthy and current.</p>"

    when = now.strftime("%Y-%m-%d %H:%M UTC")
    note = ("A dash (–) means the latest build has no test report: the shared build and the BOM have no code to test, and the "
            "demo builds with its own pipeline.")
    for r in repos:
        if not r["coverage_counts"]:
            note += f" {r['name']} shows n/a for coverage: {r['coverage_note'] or 'its coverage is not counted'}."
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Paramichha build health</title><style>{rs.CSS}ul{{padding-left:20px}}li{{margin:4px 0}}</style><body><main>'
            f'<div class="top"><div><h1>Paramichha build health</h1><p class="mute">Latest build of each repository · {rs.esc(when)}</p></div>'
            f'<span class="pill {level}">{rs.esc(v)}</span></div><p class="headline">{rs.esc(head)}</p>'
            f'<div class="cards">{"".join(cards)}</div>{look_html}<h2>Repositories</h2>{table}'
            f'<footer>{rs.esc(note)} Numbers come from each repository’s latest completed build on its main branch; '
            f'open the build to download its full report.</footer></main></body></html>')


def markdown(repos, tot, v):
    icon = {"Passing": "✅", "Needs attention": "⚠️", "Failing": "❌"}.get(v, "➖")
    lines = [f"## {icon} Paramichha build health: {v}", "", headline(tot, repos, v), "",
             "| Repository | Build | Tests | Lines | Branches | Findings | Built |", "|---|---|---|---|---|---|---|"]
    for r in repos:
        rep = r["has_report"]
        lines.append(f"| {r['name']} | {r['status']} | {r.get('tests') if rep else '–'} | {pct_cell(r, 'line_pct')} | "
                     f"{pct_cell(r, 'branch_pct')} | {r.get('findings') if rep else '–'} | {r['built_ago']} |")
    return "\n".join(lines) + "\n"


def run(data_dir, config_path, out):
    config = load(config_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    repos = collect(data_dir, config, now)
    tot = totals(repos)
    v, _ = verdict(repos)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render(repos, tot, now))
    with open(os.path.join(out, "overview.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": 1, "generated": now.isoformat(), "verdict": v, "totals": tot, "repositories": repos}, fh, indent=2)
    text = markdown(repos, tot, v)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--config", default=os.path.join(HERE, "portfolio.json"))
    ap.add_argument("--out", default="overview")
    args = ap.parse_args()
    try:
        run(args.data, args.config, args.out)
    except Exception as exc:  # best effort, like report-summary.py
        print(f"::warning title=Overview::{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
