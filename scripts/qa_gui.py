"""Run QtTest desktop acceptance; use Xvfb/xcb for a real Linux window.

xvfb-run -a python -m scripts.qa_gui --screenshots docs/qa/qt
QT_SCALE_FACTOR=2 QT_QPA_PLATFORM=offscreen python -m scripts.qa_gui
"""
import argparse
import os
import unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        os.environ['RF_QA_SCREENSHOTS'] = str(args.screenshots.resolve())
    from tests.test_gui import GuiTests
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GuiTests))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
