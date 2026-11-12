#!/usr/bin/env python3
"""One-page summary of a Maven build's reports, for people who do not read XML.

Reads what `mvn verify` wrote under target/ (test results, JaCoCo coverage, Checkstyle, PMD,
SpotBugs and PMD CPD) and writes:

  target/index.html    the one-page summary, linking to the detail pages next to it
  target/summary.json  the same numbers, for tools
  and, when GITHUB_STEP_SUMMARY is set, a short Markdown version for the run's summary page.

Best effort: if anything goes wrong it prints a warning and exits 0, so a problem in the report
never fails the build it describes. Standard library only. Usage: report-summary.py [--target target]
Environment (all optional): BUILD_RESULT (success|failure), GITHUB_REPOSITORY, GITHUB_SHA,
GITHUB_REF_NAME, GITHUB_SERVER_URL, GITHUB_RUN_ID.
"""
import argparse
import csv
import datetime
import glob
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

TOP = 8  # rows shown in each "where to look" list
SCHEMA = 1  # version of summary.json


def local(tag):
    return tag.split("}")[-1]


def short(path):
    path = (path or "").replace("\\", "/")
    for marker in ("/src/main/java/", "/src/test/java/", "/src/"):
        if marker in path:
            return path.split(marker, 1)[1]
    return path.rsplit("/", 1)[-1]


def parse(path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None


def read_tests(target):
    files = glob.glob(os.path.join(target, "surefire-reports", "TEST-*.xml"))
    if not files:
        return None
    out = {"run": 0, "failed": 0, "skipped": 0, "seconds": 0.0, "failures": []}
    for f in files:
        root = parse(f)
        if root is None:
            continue
        for case in root.iter("testcase"):
            out["run"] += 1
            out["seconds"] += float(case.get("time") or 0)
            problem = case.find("failure") if case.find("failure") is not None else case.find("error")
            if problem is not None:
                out["failed"] += 1
                message = " ".join((problem.get("message") or "").split())
                out["failures"].append(f"{case.get('classname', '').rsplit('.', 1)[-1]}.{case.get('name')}: {message[:160]}")
            elif case.find("skipped") is not None:
                out["skipped"] += 1
    return out


def read_coverage(target):
    path = os.path.join(target, "site", "jacoco", "jacoco.csv")
    if not os.path.exists(path):
        return None
    lm = lc = bm = bc = 0
    classes = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            a, b, c, d = (int(row[k]) for k in ("LINE_MISSED", "LINE_COVERED", "BRANCH_MISSED", "BRANCH_COVERED"))
            lm += a
            lc += b
            bm += c
            bc += d
            classes.append((row["CLASS"], row["PACKAGE"], a, b, c, d))
    lines, branches = lm + lc, bm + bc
    gaps = sorted((c for c in classes if c[4] or c[2]), key=lambda c: (-(c[4] + c[2]), c[0]))[:TOP]
    return {
        "lines": lines, "lines_covered": lc, "line_pct": 100.0 * lc / lines if lines else None,
        "branches": branches, "branches_covered": bc, "branch_pct": 100.0 * bc / branches if branches else None,
        "classes": len(classes),
        "gaps": [{"class": c[0], "package": c[1], "lines_missed": c[2], "branches_missed": c[4],
                  "branch_pct": 100.0 * c[5] / (c[4] + c[5]) if c[4] + c[5] else None} for c in gaps],
    }


def read_checkstyle(target):
    root = parse(os.path.join(target, "checkstyle-result.xml"))
    if root is None:
        return None
    rows = []
    for f in root.iter("file"):
        for e in f.iter("error"):
            rows.append((short(f.get("name")), e.get("line"), (e.get("message") or "")[:140]))
    return {"count": len(rows), "rows": rows[:TOP]}


def read_pmd(target):
    root = parse(os.path.join(target, "pmd.xml"))
    if root is None:
        return None
    rows = []
    for f in root.iter():
        if local(f.tag) != "file":
            continue
        for v in f:
            if local(v.tag) == "violation":
                rows.append((short(f.get("name")), v.get("beginline"), f"{v.get('rule')}: {' '.join((v.text or '').split())[:120]}"))
    return {"count": len(rows), "rows": rows[:TOP]}


def read_spotbugs(target):
    root = parse(os.path.join(target, "spotbugsXml.xml"))
    if root is None:
        return None
    rows = []
    for bug in root.iter("BugInstance"):
        src = bug.find("SourceLine")
        where = short(src.get("sourcepath")) if src is not None else bug.get("type")
        line = (src.get("start") if src is not None else "") or ""
        message = bug.findtext("LongMessage") or bug.get("type")
        rows.append((where, line, f"{bug.get('type')}: {message[:120]}"))
    return {"count": len(rows), "rows": rows[:TOP]}


def read_cpd(target):
    root = parse(os.path.join(target, "cpd.xml"))
    if root is None:
        return None
    rows, total = [], 0
    for d in root.iter():
        if local(d.tag) != "duplication":
            continue
        lines = int(d.get("lines") or 0)
        total += lines
        where = [f"{short(f.get('path'))}:{f.get('line')}" for f in d if local(f.tag) == "file"]
        rows.append((lines, " and ".join(where)))
    rows.sort(reverse=True)
    return {"count": len(rows), "lines": total, "rows": [(w, str(n), "") for n, w in rows[:TOP]]}


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def fmt_pct(x):
    return "n/a" if x is None else f"{x:.1f}%"


def build(target):
    data = {"tests": read_tests(target), "coverage": read_coverage(target), "checkstyle": read_checkstyle(target),
            "pmd": read_pmd(target), "spotbugs": read_spotbugs(target), "duplication": read_cpd(target)}
    env = os.environ
    repo = env.get("GITHUB_REPOSITORY") or os.path.basename(os.path.abspath(os.path.join(target, os.pardir)))
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    run = f"{server}/{repo}/actions/runs/{env['GITHUB_RUN_ID']}" if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY") else ""
    issues = sum(data[k]["count"] for k in ("checkstyle", "pmd", "spotbugs") if data[k])
    failed = data["tests"]["failed"] if data["tests"] else 0
    result = env.get("BUILD_RESULT", "")
    if result == "failure" or failed:
        verdict, level = "Failing", "bad"
    elif issues:
        verdict, level = "Needs attention", "warn"
    elif result == "success" or data["tests"]:
        verdict, level = "Passing", "good"
    else:
        verdict, level = "No results", "none"
    sha = env.get("GITHUB_SHA") or ""
    on_github = bool(env.get("GITHUB_REPOSITORY"))
    data["meta"] = {"project": repo.split("/")[-1], "repository": repo, "commit": sha[:7],
                    "branch": env.get("GITHUB_REF_NAME", ""), "run_url": run, "build_result": result or "unknown",
                    "repo_url": f"{server}/{repo}" if on_github else "",
                    "commit_url": f"{server}/{repo}/commit/{sha}" if on_github and sha else "",
                    "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "verdict": verdict, "issues": issues}
    data["meta"]["headline"] = headline(data, verdict, result)
    data["schema"] = SCHEMA
    return data, level


def headline(data, verdict, result):
    """One plain sentence for someone who will not read the tables."""
    t, dup = data["tests"], data["duplication"]
    issues, failed = data["meta"]["issues"], (data["tests"]["failed"] if data["tests"] else 0)
    if verdict == "Failing":
        parts = ["The build failed." if result == "failure" else "Something is failing."]
        if failed:
            parts.append(f"{plural(failed, 'test')} failing.")
        if issues:
            parts.append(f"{plural(issues, 'finding')} to fix.")
        return " ".join(parts)
    if verdict == "Needs attention":
        return f"Tests pass, but {plural(issues, 'finding')} to fix."
    if verdict == "Passing":
        text = f"All {t['run']} tests pass and every check is clean." if t else "The build passed and every check is clean."
        if dup and dup["count"]:
            text += f" {plural(dup['count'], 'duplicated block')} noted; that does not fail the build."
        return text
    return "No test or analysis results were found."


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mute:#5d6b7c;--line:#e2e6ec;--good:#1a7f4b;--warn:#b26a00;--bad:#c0392b;--none:#6b7785;--link:#1f5fbf}
@media(prefers-color-scheme:dark){:root{--bg:#10151c;--card:#18202a;--ink:#e7ecf3;--mute:#9aa7b8;--line:#2a3441;--good:#46c07f;--warn:#e5a13a;--bad:#ef6a5b;--none:#8a97a8;--link:#7fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 20px 48px}a{color:var(--link)}
h1{font-size:26px;margin:0 0 4px;overflow-wrap:anywhere}h1 a{color:inherit;text-decoration:none}h1 a:hover{text-decoration:underline}
h2{font-size:17px;margin:34px 0 10px}p{margin:0}.mute{color:var(--mute)}
.headline{font-size:17px;margin-top:14px}
.top{display:flex;flex-wrap:wrap;gap:14px;align-items:center;justify-content:space-between}
.pill{display:inline-block;padding:5px 14px;border-radius:99px;font-weight:600;color:#fff}
.pill.good{background:var(--good)}.pill.warn{background:var(--warn)}.pill.bad{background:var(--bad)}.pill.none{background:var(--none)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}
.card{display:flex;flex-direction:column;gap:2px;background:var(--card);border:1px solid var(--line);border-top:4px solid var(--none);border-radius:8px;padding:14px 16px;text-decoration:none;color:inherit}
a.card:hover{box-shadow:0 2px 10px rgba(0,0,0,.14)}a.card:focus-visible{outline:3px solid var(--link);outline-offset:2px}
.card.good{border-top-color:var(--good)}.card.warn{border-top-color:var(--warn)}.card.bad{border-top-color:var(--bad)}
.card .n{font-size:28px;font-weight:700;line-height:1.2}.card .l{font-weight:600}.card .s{font-size:13px;color:var(--mute)}
.bar{height:6px;border-radius:3px;background:var(--line);margin:4px 0 2px;overflow:hidden}.bar i{display:block;height:100%;background:var(--none)}
.card.good .bar i{background:var(--good)}.card.warn .bar i{background:var(--warn)}.card.bad .bar i{background:var(--bad)}
.foot{display:flex;justify-content:space-between;gap:8px;margin-top:8px;font-size:13px;font-weight:600}
.card.good .st{color:var(--good)}.card.warn .st{color:var(--warn)}.card.bad .st{color:var(--bad)}.card .st{color:var(--none)}.more{color:var(--link);font-weight:500}
.scroll{overflow-x:auto;border-radius:8px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);font-size:14px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600;font-size:13px}
tr:last-child td{border-bottom:0}td.num{white-space:nowrap}code{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:break-word}
.glossary{columns:2 340px;column-gap:28px;font-size:14px}.glossary dt{font-weight:600;margin-top:10px;break-after:avoid}.glossary dt:first-child{margin-top:0}.glossary dd{margin:0;color:var(--mute)}
footer{margin-top:40px;font-size:13px;color:var(--mute)}
@media print{body{background:#fff;color:#000}.card,table,dl{break-inside:avoid}a.card{box-shadow:none}.more{display:none}main{padding:0}}
"""

STATUS = {"good": ("✓", "OK"), "warn": ("!", "Watch"), "bad": ("✗", "Fix"), "none": ("–", "n/a")}


def esc(x):
    return html.escape(str(x))


def table(head, rows, code_cols=()):
    def cell(i, c):
        text = esc(c)
        return f"<td>{'<code>' + text + '</code>' if i in code_cols else text}</td>"
    body = "".join("<tr>" + "".join(cell(i, c) for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<div class=\"scroll\"><table><tr>{''.join(f'<th>{esc(h)}</th>' for h in head)}</tr>{body}</table></div>"


def render(data, level, target="."):
    m, t, cov = data["meta"], data["tests"], data["coverage"]
    cs, pm, sb, dup = data["checkstyle"], data["pmd"], data["spotbugs"], data["duplication"]

    def card(label, number, sub, link, status, pct=None):
        icon, word = STATUS[status]
        bar = f'<div class="bar"><i style="width:{max(0.0, min(100.0, pct)):.1f}%"></i></div>' if pct is not None else ""
        live = os.path.exists(os.path.join(target, link))  # no link to a page that was not written
        tag, href = ("a", f' href="{esc(link)}"') if live else ("div", "")
        more = '<span class="more">Details →</span>' if live else ""
        return (f'<{tag} class="card {status}"{href}><div class="l">{esc(label)}</div><div class="n">{esc(number)}</div>{bar}'
                f'<div class="s">{esc(sub)}</div><div class="foot"><span class="st">{icon} {word}</span>{more}</div></{tag}>')

    cards = []
    if t:
        cards.append(card("Tests", f"{t['run'] - t['failed'] - t['skipped']}/{t['run']}",
                          f"passed in {t['seconds']:.0f}s" + (f", {t['failed']} failed" if t["failed"] else ""),
                          "site/surefire-report.html", "bad" if t["failed"] else "good"))
    if cov:
        for label, pct, covd, total in (("Line coverage", cov["line_pct"], cov["lines_covered"], cov["lines"]),
                                        ("Branch coverage", cov["branch_pct"], cov["branches_covered"], cov["branches"])):
            status = "none" if pct is None else "good" if pct >= 90 else "warn" if pct >= 75 else "bad"
            cards.append(card(label, fmt_pct(pct), f"{covd} of {total} run by tests", "site/jacoco/index.html", status, pct))
    for label, d, link in (("Style (Checkstyle)", cs, "reports/checkstyle.html"), ("Code smells (PMD)", pm, "reports/pmd.html"),
                           ("Bug patterns (SpotBugs)", sb, "reports/spotbugs.html")):
        if d:
            cards.append(card(label, d["count"], "no findings" if not d["count"] else plural(d["count"], "finding") + " to fix", link,
                              "good" if not d["count"] else "bad"))
    if dup:
        cards.append(card("Duplicated code", dup["count"], plural(dup["lines"], "repeated line") if dup["count"] else "none found",
                          "reports/cpd.html", "good" if not dup["count"] else "warn"))

    name = f'<a href="{esc(m["repo_url"])}">{esc(m["project"])}</a>' if m["repo_url"] else esc(m["project"])
    commit = (f' · commit <a href="{esc(m["commit_url"])}">{esc(m["commit"])}</a>' if m["commit_url"]
              else f' · commit {esc(m["commit"])}' if m["commit"] else "")
    parts = [f'<div class="top"><div><h1>{name}</h1><p class="mute">Build report'
             f'{" · branch " + esc(m["branch"]) if m["branch"] else ""}{commit} · {esc(m["generated"])}</p></div>'
             f'<span class="pill {level}">{esc(m["verdict"])}</span></div>',
             f'<p class="headline">{esc(m["headline"])}</p>',
             f'<div class="cards">{"".join(cards)}</div>']

    if cov and cov["gaps"]:
        parts.append("<h2>Where the tests do not reach</h2><p class=\"mute\">Classes with the most code paths no test runs. "
                     "A good place to add tests next.</p>")
        parts.append(table(["Class", "Package", "Lines not run", "Branches not run", "Branch coverage"],
                           [(g["class"], g["package"], g["lines_missed"], g["branches_missed"], fmt_pct(g["branch_pct"]))
                            for g in cov["gaps"]], code_cols=(0,)))
    if t and t["failures"]:
        parts.append("<h2>Failing tests</h2>" + table(["Test"], [(f,) for f in t["failures"][:TOP * 2]], code_cols=(0,)))
    for label, d in (("Style findings", cs), ("Code smell findings", pm), ("Bug pattern findings", sb)):
        if d and d["count"]:
            parts.append(f"<h2>{esc(label)} ({d['count']})</h2>" + table(["File", "Line", "Finding"], d["rows"], code_cols=(0,)))
    if dup and dup["count"]:
        parts.append("<h2>Repeated code</h2><p class=\"mute\">The same block in more than one place costs more to change safely. "
                     "Informational: it does not fail the build.</p>" + table(["Where", "Lines", ""], dup["rows"], code_cols=(0,)))

    parts.append("""<h2>What these mean</h2><dl class="glossary">
<dt>Tests</dt><dd>Automatic checks that the code still does what it should. Any failure fails the build.</dd>
<dt>Line and branch coverage</dt><dd>How much of the code the tests actually run. Lines are the plain measure; branches count each side of every if. Low numbers hide untested behaviour.</dd>
<dt>Style, code smells, bug patterns</dt><dd>Three automatic reviewers: Checkstyle for style, PMD for suspicious code, SpotBugs for patterns that usually mean a bug. Any finding fails the build.</dd>
<dt>Formatting</dt><dd>Spotless checks the layout of every file. It has no page: a layout problem fails the build with the file names in the log.</dd>
<dt>Duplicated code</dt><dd>Copy-pasted blocks. Informational only.</dd></dl>""")
    link = f' · <a href="{esc(m["run_url"])}">Open this run on GitHub</a>' if m["run_url"] else ""
    parts.append(f'<footer>Numbers come from this build’s own reports; the cards open the detail pages next to this file{link}.</footer>')
    return f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
           f'<title>{esc(m["project"])} build report</title><style>{CSS}</style><body><main>{"".join(parts)}</main></body></html>'


def markdown(data, level):
    m, t, cov = data["meta"], data["tests"], data["coverage"]
    icon = {"good": "✅", "warn": "⚠️", "bad": "❌", "none": "➖"}[level]
    lines = [f"## {icon} {m['project']}: {m['verdict']}", "", m["headline"], ""]
    rows = []
    if t:
        rows.append(("Tests", f"{t['run'] - t['failed'] - t['skipped']} of {t['run']} passed, {t['failed']} failed, {t['skipped']} skipped"))
    if cov:
        rows.append(("Coverage", f"{fmt_pct(cov['line_pct'])} of lines, {fmt_pct(cov['branch_pct'])} of branches"))
    for label, key in (("Checkstyle", "checkstyle"), ("PMD", "pmd"), ("SpotBugs", "spotbugs")):
        if data[key]:
            rows.append((label, plural(data[key]["count"], "finding")))
    if data["duplication"]:
        rows.append(("Duplicated code", plural(data["duplication"]["count"], "block")))
    if not rows:
        return "## Build report\n\nNo reports: this project has no Java sources.\n"
    lines += ["| Check | Result |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows]
    lines += ["", "Download **reports** below, unzip it and open **index.html** for the one-page summary."]
    return "\n".join(lines) + "\n"


def run(target):
    data, level = build(target)
    has_results = any(data[k] for k in ("tests", "coverage", "checkstyle", "pmd", "spotbugs", "duplication"))
    if has_results:
        with open(os.path.join(target, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(render(data, level, target))
        with open(os.path.join(target, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
    text = markdown(data, level)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="target")
    try:
        run(ap.parse_args().target)
    except Exception as exc:  # best effort: a problem in the report must never fail the build it describes
        print(f"::warning title=Report summary::{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
