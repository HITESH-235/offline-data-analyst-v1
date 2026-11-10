"""Repeatable regression milestone. Refuse unexpected Python HTTP/model requests.

Run from server: python scripts/replay_analysis_checks.py
Model behavior is replayed; calculations, subprocesses and storage are real.
"""
import sys
import urllib.request
from urllib.parse import urlparse
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=='__main__':
    tests=Path(__file__).resolve().parents[1]/'tests'
    suite=unittest.defaultTestLoader.discover(str(tests))
    original_open = urllib.request.OpenerDirector.open
    def local_fixture_only(opener, request, *args, **kwargs):
        url = request.full_url if hasattr(request, 'full_url') else request
        parsed = urlparse(url)
        method = request.get_method() if hasattr(request, 'get_method') else 'GET'
        if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.path != '/' or method != 'GET':
            raise AssertionError('Live HTTP/model calls are disabled during regression replay.')
        return original_open(opener, request, *args, **kwargs)
    with patch('urllib.request.urlopen',side_effect=AssertionError('Live HTTP/model calls are disabled during regression replay.')), patch('urllib.request.OpenerDirector.open', local_fixture_only):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
