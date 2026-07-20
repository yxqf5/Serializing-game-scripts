# -*- coding: utf-8 -*-
"""运行测试：python run_tests.py"""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(BASE, "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
