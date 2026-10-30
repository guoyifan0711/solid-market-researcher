"""Run the synthetic regression suite with temporary files inside the checkout."""
from pathlib import Path
import sys
import tempfile
import unittest


def main():
    root = Path(__file__).resolve().parents[1]
    scripts = root / "skills" / "review-market-analysis" / "scripts"
    work = root / "tmp" / "tests"
    work.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(work)
    sys.path.insert(0, str(scripts))
    suite = unittest.defaultTestLoader.discover(str(scripts), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
