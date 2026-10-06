"""Golden runs only (tests/golden/golden.py puts this folder first on PYTHONPATH): makes each child
process deterministic without touching the code under test.

- the test network guard (tests/netguard/mb_netguard.py) is installed, as in the test suite;
- every DuckDB connection runs on one thread, so rows of a query without a full ORDER BY come back
  in file order every time (several scripts write such rows; with parallel scans their order, and
  float sums over them, vary between runs);
- then the interpreter's own sitecustomize runs, if there is one."""
import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_netguard = os.path.join(os.path.dirname(os.path.dirname(_here)), "netguard")

if os.environ.get("MB_NETGUARD"):
    sys.path.insert(0, _netguard)
    try:
        import mb_netguard
        mb_netguard.install()
    finally:
        sys.path.remove(_netguard)

import duckdb  # noqa: E402

_duckdb_connect = duckdb.connect


def _single_thread_connect(*args, **kwargs):
    """duckdb.connect with threads = 1."""
    connection = _duckdb_connect(*args, **kwargs)
    connection.execute("SET threads TO 1")
    return connection


duckdb.connect = _single_thread_connect

for _path in sys.path:
    if os.path.abspath(_path or os.getcwd()) in (_here, _netguard):
        continue
    _file = os.path.join(_path, "sitecustomize.py")
    if os.path.isfile(_file):
        _spec = importlib.util.spec_from_file_location("_mb_original_sitecustomize", _file)
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        break
