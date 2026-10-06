"""Test-only: loads the network guard (mb_netguard.py) into every child Python process that a test
starts, because tests/conftest.py puts this folder on PYTHONPATH. Then runs the interpreter's own
sitecustomize, if there is one, so nothing else changes."""
import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))

if os.environ.get("MB_NETGUARD"):
    sys.path.insert(0, _here)
    try:
        import mb_netguard
        mb_netguard.install()
    finally:
        sys.path.remove(_here)

for _p in sys.path:
    if os.path.abspath(_p or os.getcwd()) == _here:
        continue
    _f = os.path.join(_p, "sitecustomize.py")
    if os.path.isfile(_f):
        _spec = importlib.util.spec_from_file_location("_mb_original_sitecustomize", _f)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        break
