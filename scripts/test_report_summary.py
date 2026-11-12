"""Tests for report-summary.py. Run: python3 -m unittest discover -s scripts -p 'test_*.py'"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("report_summary", os.path.join(HERE, "report-summary.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

PASSING = '<testsuite><testcase classname="a.B" name="one" time="0.5"/><testcase classname="a.B" name="two" time="0.5"/></testsuite>'
FAILING = ('<testsuite><testcase classname="a.B" name="one" time="0.5"/>'
           '<testcase classname="a.B" name="two"><failure message="expected: 1 but was: 2">trace</failure></testcase></testsuite>')
JACOCO = ("GROUP,PACKAGE,CLASS,INSTRUCTION_MISSED,INSTRUCTION_COVERED,BRANCH_MISSED,BRANCH_COVERED,LINE_MISSED,LINE_COVERED,"
          "COMPLEXITY_MISSED,COMPLEXITY_COVERED,METHOD_MISSED,METHOD_COVERED\n"
          "app,com.acme,Foo,0,10,2,6,0,10,0,3,0,3\napp,com.acme,Bar,0,10,0,4,0,10,0,2,0,2\n")
CHECKSTYLE_CLEAN = '<?xml version="1.0"?><checkstyle version="14"><file name="/x/src/main/java/a/B.java"/></checkstyle>'
PMD_CLEAN = '<pmd xmlns="http://pmd.sourceforge.net/report/2.0.0" version="7"/>'
SPOTBUGS_CLEAN = '<BugCollection version="4"/>'
CPD_CLEAN = '<pmd-cpd/>'


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, "target")
        self.env = mock.patch.dict(os.environ, {"BUILD_RESULT": "success", "GITHUB_REPOSITORY": "acme/widgets", "GITHUB_SHA": "abcdef1234567",
                                                "GITHUB_REF_NAME": "main", "GITHUB_RUN_ID": "7"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)

    def reports(self, tests=PASSING, checkstyle=CHECKSTYLE_CLEAN, pmd=PMD_CLEAN, spotbugs=SPOTBUGS_CLEAN, cpd=CPD_CLEAN):
        t = self.target
        write(f"{t}/surefire-reports/TEST-a.B.xml", tests)
        write(f"{t}/site/jacoco/jacoco.csv", JACOCO)
        write(f"{t}/checkstyle-result.xml", checkstyle)
        write(f"{t}/pmd.xml", pmd)
        write(f"{t}/spotbugsXml.xml", spotbugs)
        write(f"{t}/cpd.xml", cpd)
        for page in ("site/surefire-report.html", "site/jacoco/index.html", "reports/checkstyle.html", "reports/pmd.html",
                     "reports/spotbugs.html", "reports/cpd.html"):
            write(f"{t}/{page}", "<html/>")

    def call_main(self):
        with mock.patch("sys.argv", ["report-summary.py", "--target", self.target]), contextlib.redirect_stdout(io.StringIO()):
            return rs.main()


class Summary(Fixture):
    def test_a_clean_build_is_passing_and_the_numbers_are_right(self):
        self.reports()
        self.assertEqual(self.call_main(), 0)
        data = json.loads(read(os.path.join(self.target, "summary.json")))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["meta"]["verdict"], "Passing")
        self.assertEqual((data["tests"]["run"], data["tests"]["failed"]), (2, 0))
        self.assertEqual(data["coverage"]["line_pct"], 100.0)
        self.assertEqual(data["coverage"]["branch_pct"], 100.0 * 10 / 12)
        self.assertEqual(data["coverage"]["gaps"][0]["class"], "Foo")
        self.assertEqual(data["coverage"]["gaps"][0]["branch_pct"], 75.0)
        self.assertEqual(data["meta"]["headline"], "All 2 tests pass and every check is clean.")

    def test_the_page_links_the_repository_the_commit_and_the_detail_pages(self):
        self.reports()
        self.call_main()
        page = read(os.path.join(self.target, "index.html"))
        for expected in ('href="https://github.com/acme/widgets"', 'href="https://github.com/acme/widgets/commit/abcdef1234567"',
                         'href="site/jacoco/index.html"', 'href="reports/pmd.html"', 'class="pill good">Passing'):
            self.assertIn(expected, page)

    def test_a_failing_test_makes_the_build_failing_and_is_listed(self):
        self.reports(tests=FAILING)
        self.call_main()
        page = read(os.path.join(self.target, "index.html"))
        self.assertIn("Failing", page)
        self.assertIn("a.B".rsplit(".", 1)[-1] + ".two: expected: 1 but was: 2", page)

    def test_findings_without_a_failed_build_need_attention(self):
        bug = '<BugCollection><BugInstance type="X_Y"><LongMessage>bad</LongMessage><SourceLine sourcepath="a/B.java" start="4"/></BugInstance></BugCollection>'
        self.reports(spotbugs=bug)
        self.call_main()
        data = json.loads(read(os.path.join(self.target, "summary.json")))
        self.assertEqual((data["meta"]["verdict"], data["meta"]["issues"]), ("Needs attention", 1))

    def test_a_failed_build_is_failing_even_when_every_report_is_clean(self):
        self.reports()
        os.environ["BUILD_RESULT"] = "failure"
        self.call_main()
        data = json.loads(read(os.path.join(self.target, "summary.json")))
        self.assertEqual(data["meta"]["verdict"], "Failing")
        self.assertTrue(data["meta"]["headline"].startswith("The build failed."))

    def test_report_text_cannot_inject_markup(self):
        evil = '<checkstyle><file name="/x/src/main/java/a/B.java"><error line="1" message="&lt;script&gt;alert(1)&lt;/script&gt;"/></file></checkstyle>'
        self.reports(checkstyle=evil)
        self.call_main()
        page = read(os.path.join(self.target, "index.html"))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_a_card_has_no_link_when_its_page_was_not_written(self):
        self.reports()
        os.remove(os.path.join(self.target, "reports", "cpd.html"))
        self.call_main()
        page = read(os.path.join(self.target, "index.html"))
        self.assertNotIn('href="reports/cpd.html"', page)
        self.assertIn('href="reports/pmd.html"', page)

    def test_no_reports_writes_no_page_and_says_so(self):
        os.makedirs(self.target)
        with mock.patch("builtins.print") as printed:
            self.assertEqual(self.call_main(), 0)
        self.assertFalse(os.path.exists(os.path.join(self.target, "index.html")))
        self.assertIn("no Java sources", str(printed.call_args_list))

    def test_a_malformed_report_is_skipped_not_fatal(self):
        self.reports(pmd="<pmd><file")
        self.assertEqual(self.call_main(), 0)
        data = json.loads(read(os.path.join(self.target, "summary.json")))
        self.assertIsNone(data["pmd"])

    def test_a_bug_in_the_script_never_fails_the_build(self):
        self.reports()
        with mock.patch.object(rs, "build", side_effect=RuntimeError("boom")), mock.patch("builtins.print") as printed:
            self.assertEqual(self.call_main(), 0)
        self.assertIn("::warning", str(printed.call_args_list))

    def test_the_run_summary_page_gets_the_markdown(self):
        self.reports()
        out = os.path.join(self.tmp.name, "step.md")
        os.environ["GITHUB_STEP_SUMMARY"] = out
        self.call_main()
        text = read(out)
        self.assertIn("| Tests | 2 of 2 passed", text)
        self.assertIn("open **index.html**", text)

    def test_plural(self):
        self.assertEqual((rs.plural(1, "finding"), rs.plural(2, "finding"), rs.plural(0, "block")), ("1 finding", "2 findings", "0 blocks"))


if __name__ == "__main__":
    unittest.main()
