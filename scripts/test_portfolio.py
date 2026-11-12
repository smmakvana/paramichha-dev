"""Tests for portfolio.py. Run: python3 -m unittest discover -s scripts -p 'test_*.py'"""
import contextlib
import datetime
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("portfolio", os.path.join(HERE, "portfolio.py"))
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

NOW = datetime.datetime(2026, 11, 12, 12, 0, tzinfo=datetime.timezone.utc)


def iso(**delta):
    return (NOW - datetime.timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def summary(tests=100, failed=0, lines=(100, 100), branches=(90, 100), issues=0, dup=0, verdict="Passing"):
    return {"meta": {"verdict": verdict, "issues": issues}, "tests": {"run": tests, "failed": failed},
            "coverage": {"lines": lines[1], "lines_covered": lines[0], "branches": branches[1], "branches_covered": branches[0],
                         "line_pct": 100.0 * lines[0] / lines[1], "branch_pct": 100.0 * branches[0] / branches[1]},
            "duplication": {"count": dup}}


class Portfolio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        self.config = {"owner": "acme", "stale_days": 14, "repos": []}

    def repo(self, name, conclusion="success", built=None, report=None, entry=None, about="Does a thing", updated=None):
        self.config["repos"].append({"name": name, "about": about, **(entry or {})})
        folder = os.path.join(self.data, name)
        os.makedirs(folder, exist_ok=True)
        if conclusion is not None:
            with open(os.path.join(folder, "run.json"), "w") as fh:
                run = {"databaseId": 1, "conclusion": conclusion, "createdAt": built or iso(hours=2),
                       "url": f"https://github.com/acme/{name}/actions/runs/1", "headSha": "abcdef1234"}
                if updated:
                    run["updatedAt"] = updated
                json.dump(run, fh)
        if report is not None:
            with open(os.path.join(folder, "summary.json"), "w") as fh:
                fh.write(report if isinstance(report, str) else json.dumps(report))

    def rows(self):
        return {r["name"]: r for r in pf.collect(self.data, self.config, NOW)}

    def page(self):
        repos = pf.collect(self.data, self.config, NOW)
        return pf.render(repos, pf.totals(repos), NOW)

    def test_healthy_repositories_pass_and_the_totals_add_up(self):
        self.repo("a", report=summary(tests=100, lines=(90, 100), branches=(45, 50)))
        self.repo("b", report=summary(tests=50, lines=(10, 100), branches=(5, 50)))
        repos = pf.collect(self.data, self.config, NOW)
        tot = pf.totals(repos)
        self.assertEqual((tot["tests"], tot["passing"], tot["repositories"]), (150, 2, 2))
        self.assertEqual(tot["line_pct"], 50.0)
        self.assertEqual(tot["branch_pct"], 50.0)
        self.assertEqual(pf.verdict(repos), ("Passing", "good"))
        self.assertEqual(pf.headline(tot, repos, "Passing"), "All 2 repositories build cleanly. 150 tests ran and all pass.")

    def test_a_failed_build_fails_the_overview_and_comes_first_in_worth_a_look(self):
        self.repo("good", report=summary())
        self.repo("broken", conclusion="failure", report=summary())
        repos = pf.collect(self.data, self.config, NOW)
        self.assertEqual(pf.verdict(repos), ("Failing", "bad"))
        self.assertTrue(pf.attention(repos)[0].startswith("broken: failing"))
        self.assertIn("look at broken", pf.headline(pf.totals(repos), repos, "Failing"))

    def test_an_old_build_is_stale_and_needs_attention(self):
        self.repo("old", built=iso(days=20))
        row = self.rows()["old"]
        self.assertEqual((row["status"], row["built_ago"]), ("Stale", "20 days ago"))
        self.assertEqual(pf.verdict(list(self.rows().values()))[0], "Needs attention")

    def test_a_repository_that_cannot_be_read_says_so_and_names_the_likely_cause(self):
        self.repo("hidden", conclusion=None)
        with open(os.path.join(self.data, "hidden", "run.json"), "w") as fh:
            json.dump({"unreadable": True}, fh)
        row = self.rows()["hidden"]
        self.assertEqual((row["status"], row["level"]), ("Not readable", "warn"))
        self.assertIn("If it is private", pf.attention(list(self.rows().values()))[0])
        self.assertEqual(pf.verdict(list(self.rows().values()))[0], "Needs attention")

    def test_the_page_says_only_public_repositories_are_listed(self):
        self.repo("a", report=summary())
        self.assertIn("Only public repositories are listed", self.page())

    def test_a_repository_with_no_build_is_reported_not_skipped(self):
        self.repo("new", conclusion=None)
        self.assertEqual(self.rows()["new"]["status"], "No build")
        self.assertIn("no build was found", pf.attention(list(self.rows().values()))[0])

    def test_a_re_run_counts_as_built_when_its_latest_attempt_ended(self):
        self.repo("rerun", built=iso(days=20), updated=iso(minutes=30))
        row = self.rows()["rerun"]
        self.assertEqual((row["status"], row["built_ago"]), ("Passing", "just now"))

    def test_a_report_that_says_failing_beats_a_green_run(self):
        self.repo("odd", report=summary(verdict="Failing"))
        self.assertEqual(self.rows()["odd"]["status"], "Failing")

    def test_repositories_without_a_report_are_listed_with_dashes(self):
        self.repo("bom")
        self.assertEqual(self.rows()["bom"]["status"], "Passing")
        self.assertIn("<td class=\"num\">–</td>", self.page())

    def test_sample_classes_are_left_out_of_coverage_and_shown_as_n_a(self):
        self.repo("lib", report=summary(lines=(100, 100), branches=(50, 50)))
        self.repo("catalog", report=summary(tests=5, lines=(2, 100), branches=(0, 50)),
                  entry={"coverage": False, "coverage_note": "sample classes"})
        repos = pf.collect(self.data, self.config, NOW)
        tot = pf.totals(repos)
        self.assertEqual((tot["line_pct"], tot["branch_pct"], tot["tests"]), (100.0, 100.0, 105))
        self.assertEqual(pf.pct_cell(repos[1], "line_pct"), "n/a")
        self.assertFalse([t for t in pf.attention(repos) if "catalog" in t])
        self.assertIn("catalog shows n/a for coverage: sample classes", pf.render(repos, tot, NOW))

    def test_low_branch_coverage_is_flagged_lowest_first(self):
        self.repo("a", report=summary(branches=(85, 100)))
        self.repo("b", report=summary(branches=(70, 100)))
        notes = [t for t in pf.attention(list(self.rows().values())) if "branch coverage" in t]
        self.assertEqual([n.split(":")[0] for n in notes], ["b", "a"])

    def test_text_from_the_config_cannot_inject_markup(self):
        self.repo("x", about="<script>alert(1)</script>")
        page = self.page()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_a_broken_summary_file_is_treated_as_no_report(self):
        self.repo("x", report="{not json")
        self.assertFalse(self.rows()["x"]["has_report"])

    def test_run_writes_the_page_the_json_and_the_summary_table(self):
        self.repo("a", report=summary())
        cfg = os.path.join(self.tmp.name, "portfolio.json")
        with open(cfg, "w") as fh:
            json.dump(self.config, fh)
        out, step = os.path.join(self.tmp.name, "out"), os.path.join(self.tmp.name, "step.md")
        with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": step}), contextlib.redirect_stdout(io.StringIO()):
            pf.run(self.data, cfg, out)
        with open(os.path.join(out, "overview.json")) as fh:
            self.assertEqual(json.load(fh)["schema"], 1)
        self.assertTrue(os.path.exists(os.path.join(out, "index.html")))
        with open(step) as fh:
            self.assertIn("| a | Passing | 100 |", fh.read())

    def test_a_bug_never_fails_the_workflow(self):
        with mock.patch.object(pf, "run", side_effect=RuntimeError("boom")), mock.patch("sys.argv", ["portfolio.py"]), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(pf.main(), 0)
        self.assertIn("::warning", str(printed.call_args_list))

    def test_ago(self):
        then = lambda **d: NOW - datetime.timedelta(**d)
        self.assertEqual([pf.ago(then(minutes=5), NOW), pf.ago(then(hours=1), NOW), pf.ago(then(days=1), NOW), pf.ago(None, NOW)],
                         ["just now", "1 hour ago", "1 day ago", "never"])


if __name__ == "__main__":
    unittest.main()
