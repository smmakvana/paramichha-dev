"""Exercise the checkout migration against real Git attributes and CRLF bytes."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("normalize-line-endings.py")
SPEC = importlib.util.spec_from_file_location("normalize_line_endings", SCRIPT)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class NormalizeLineEndingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="checkout with spaces ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        (self.root / ".gitattributes").write_bytes(
            b"* text=auto eol=lf\n*.bin binary\nkeep.txt text eol=crlf\n"
        )
        (self.root / "edited file.java").write_bytes(b"original\n")
        (self.root / "binary.bin").write_bytes(b"binary\r\n")
        (self.root / "keep.txt").write_bytes(b"keep\r\n")
        self.git("add", ".")
        (self.root / "edited file.java").write_bytes(b"original\r\nlocal edit\r\n")
        (self.root / "untracked.java").write_bytes(b"untracked\r\n")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE)

    def test_repairs_crlf_and_preserves_edits_index_and_other_files(self):
        index = self.git("ls-files", "--stage")
        self.assertEqual(1, migration.normalize(self.root))
        self.assertEqual(b"original\nlocal edit\n", (self.root / "edited file.java").read_bytes())
        self.assertEqual(index, self.git("ls-files", "--stage"))
        self.assertEqual(b"binary\r\n", (self.root / "binary.bin").read_bytes())
        self.assertEqual(b"keep\r\n", (self.root / "keep.txt").read_bytes())
        self.assertEqual(b"untracked\r\n", (self.root / "untracked.java").read_bytes())
        self.assertEqual(0, migration.normalize(self.root))

    def test_check_returns_nonzero_without_modifying_files(self):
        command = [sys.executable, str(SCRIPT), "--check", str(self.root)]
        self.assertEqual(1, subprocess.run(command, capture_output=True).returncode)
        self.assertIn(b"\r\n", (self.root / "edited file.java").read_bytes())
        migration.normalize(self.root)
        self.assertEqual(0, subprocess.run(command, capture_output=True).returncode)

    def test_mixed_line_endings_and_missing_files(self):
        (self.root / "edited file.java").write_bytes(b"first\nsecond\r\nthird\n")
        (self.root / "keep.txt").unlink()
        self.assertEqual(1, migration.normalize(self.root))
        self.assertEqual(b"first\nsecond\nthird\n", (self.root / "edited file.java").read_bytes())

    def test_nul_bytes_are_never_rewritten(self):
        (self.root / "edited file.java").write_bytes(b"\0binary\r\n")
        self.assertEqual(0, migration.normalize(self.root))
        self.assertEqual(b"\0binary\r\n", (self.root / "edited file.java").read_bytes())


if __name__ == "__main__":
    unittest.main()
