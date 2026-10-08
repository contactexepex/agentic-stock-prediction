"""Issue #47: DuckDB's one read_csv over a glob silently drops every file whose line ending differs from the first
file's. The collect gate blocks on any stored CSV with a bare-LF line (CSV_LINE_ENDINGS), and .gitattributes keeps
git from converting the stored CRLF files."""
from __future__ import annotations

import subprocess
from pathlib import Path

import duckdb

from test_validate import MARKET, codes, root, run  # noqa: F401  (root is a fixture)

REPO = Path(__file__).resolve().parents[1]


def test_duckdb_glob_read_drops_a_file_with_other_line_endings(tmp_path):
    """The hazard itself (DuckDB 1.5.6): the LF file vanishes from one glob read without an error."""
    (tmp_path / "1.csv").write_bytes(b"a,b\r\n1,2\r\n")
    (tmp_path / "2.csv").write_bytes(b"a,b\n3,4\n")
    rows = duckdb.sql(f"SELECT * FROM read_csv('{tmp_path.as_posix()}/*.csv', header=true, "
                      "columns={'a': 'INT', 'b': 'INT'})").fetchall()
    assert rows == [(1, 2)]


def test_collect_blocks_on_an_lf_price_file_of_any_day(root):  # noqa: F811
    assert "CSV_LINE_ENDINGS" not in codes(run("collect"))          # csv.writer writes CRLF
    old = root / "data" / MARKET / "prices" / "2026" / "09" / "2026-09-28.csv"   # not today's file
    old.write_bytes(old.read_bytes().replace(b"\r\n", b"\n"))
    failure = codes(run("collect"))["CSV_LINE_ENDINGS"]
    assert "2026-09-28.csv" in failure["detail"] and "bare LF" in failure["detail"]


def test_one_bare_lf_line_is_a_problem(tmp_path, monkeypatch):
    """A mixed file (DuckDB raises a sniffing error on it, before any gate runs) is named too."""
    import common
    from marketbrief.pipeline.validate import row_checks
    monkeypatch.setattr(common, "ROOT", tmp_path)
    path = tmp_path / "x.csv"
    path.write_bytes(b"a,b\r\n1,2\r\n3,4\n")
    assert "1 of 3 lines" in row_checks.csv_line_ending_problem(path)
    path.write_bytes(b"a,b\r\n1,2\r\n")
    assert row_checks.csv_line_ending_problem(path) is None


def test_stored_csvs_are_never_converted_by_git():
    out = subprocess.run(["git", "-C", str(REPO), "check-attr", "text", "data/us/prices/2026/10/2026-10-06.csv"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip().endswith("text: unset")
