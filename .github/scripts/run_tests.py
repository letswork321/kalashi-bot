"""Run the complete suite; expose actionable tracebacks as CI annotations too."""
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
for test, traceback in result.failures + result.errors:
    message = (str(test) + '\n' + traceback).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print('::error::' + message, flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)
