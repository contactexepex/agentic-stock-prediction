"""Golden runs only (tests/golden/golden.py puts this folder first on PYTHONPATH): makes each child
process deterministic without touching the code under test.

- the test network guard (tests/netguard/mb_netguard.py) is installed, as in the test suite;
- DuckDB keeps its default threads, as in production: every query whose row order or float sum
  reaches an output has a full ORDER BY or an order-independent aggregate (docs/REFACTOR_PLAN.md,
  "Known nondeterminism", fixed), so the outputs do not depend on the thread count.
  GOLDEN_DUCKDB_THREADS=N sets N threads on every connection (e.g. a high count to stress that);
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

if os.environ.get("GOLDEN_DUCKDB_THREADS"):
    import duckdb

    _duckdb_connect = duckdb.connect
    _threads = int(os.environ["GOLDEN_DUCKDB_THREADS"])

    def _connect_with_threads(*args, **kwargs):
        """duckdb.connect with threads = GOLDEN_DUCKDB_THREADS."""
        connection = _duckdb_connect(*args, **kwargs)
        connection.execute(f"SET threads TO {_threads}")
        return connection

    duckdb.connect = _connect_with_threads

for _path in sys.path:
    if os.path.abspath(_path or os.getcwd()) in (_here, _netguard):
        continue
    _file = os.path.join(_path, "sitecustomize.py")
    if os.path.isfile(_file):
        _spec = importlib.util.spec_from_file_location("_mb_original_sitecustomize", _file)
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        break
