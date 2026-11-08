"""Repeatable regression milestone. Refuse unexpected Python HTTP/model requests.

Run from server: python scripts/replay_analysis_checks.py
Model behavior is replayed; calculations, subprocesses and storage are real.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=='__main__':
    tests=Path(__file__).resolve().parents[1]/'tests'
    suite=unittest.defaultTestLoader.discover(str(tests))
    with patch('urllib.request.urlopen',side_effect=AssertionError('Live HTTP/model calls are disabled during regression replay.')):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
