#!/usr/bin/env python3
"""Repair existing checkouts after adopting eol=lf, without discarding edits.

Usage (Python 3, Git, Windows or Unix):
    python scripts/normalize-line-endings.py ../paramichha-datafactory ../paramichha-testkit
    python scripts/normalize-line-endings.py --check ../paramichha-datafactory

Only tracked files whose effective Git attribute is eol=lf are eligible.
The index, untracked files, binary files and symlinks are left alone.
"""

import argparse
import os
from pathlib import Path
import subprocess


def normalize(repository, check=False):
    root = Path(subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip())
    entries = subprocess.check_output(["git", "-C", str(root), "ls-files", "--eol", "-z"])
    changed = 0
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        if b"eol=lf" not in metadata.split() or b"attr/-text" in metadata.split():
            continue
        path = root / os.fsdecode(name)
        if path.is_symlink() or not path.is_file():
            continue
        original = path.read_bytes()
        if b"\0" in original or b"\r\n" not in original:
            continue
        changed += 1
        print(f"{'Needs LF' if check else 'Normalized'}: {path}")
        if not check:
            path.write_bytes(original.replace(b"\r\n", b"\n"))
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report only; exit 1 if repair is needed")
    parser.add_argument("repositories", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        changed = sum(normalize(repo, args.check) for repo in args.repositories)
    except (OSError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Cannot normalize checkout: {error}\n")
    print(f"{changed} file(s) {'need LF' if args.check else 'normalized'}.")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
