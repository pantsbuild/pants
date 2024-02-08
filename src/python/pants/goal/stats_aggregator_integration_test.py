# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from pathlib import Path

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_counters_and_histograms() -> None:
    # To get the cache read histogram, we must ensure the cache is populated, so we run twice.
    with setup_tmpdir(
        {"src/py/app.py": "print(0)\n", "src/py/BUILD": "python_sources()"}
    ) as tmpdir:
        argv = [
            "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black']",
            "--plugins=hdrhistogram",
            "--stats-log",
            "lint",
            f"{tmpdir}::",
        ]
        run_pants(argv).assert_success()
        result = run_pants(argv)
    result.assert_success()
    assert "Counters:" in result.stderr
    assert re.search(r"local_cache_requests: \d", result.stderr)
    assert "remote_cache_requests: 0" in result.stderr
    assert "Observation histogram summaries" in result.stderr
    assert "Summary of `local_store_read_blob_size` observation histogram:" in result.stderr
    assert re.search(r"min: \d", result.stderr)
    assert re.search(r"p25: \d", result.stderr)
    assert re.search(r"p99: \d", result.stderr)


def test_memory_summary() -> None:
    result = run_pants(["--stats-memory-summary", "--version"])
    result.assert_success()
    assert "Memory summary" in result.stderr
    assert "pants.engine.unions.UnionMembership" in result.stderr


def test_warn_if_no_histograms() -> None:
    result = run_pants(["--stats-log", "roots"])
    result.assert_success()
    assert "Counters:" in result.stderr
    assert "Please run with `--plugins=hdrhistogram`" in result.stderr
    assert "Observation histogram summaries:" not in result.stderr


def test_writing_to_output_file() -> None:
    with setup_tmpdir({"src/py/app.py": "print(0)\n", "src/py/BUILD": "python_sources()"}):
        argv = [
            "--backend-packages=['pants.backend.python']",
            "--stats-log",
            "--stats-memory-summary",
            "--stats-output-file=stats.txt",
            "roots",
        ]
        run_pants(argv).assert_success()
        output_file_contents = Path("stats.txt").read_text()
        for item in ("Counters:", "Memory summary"):
            assert item in output_file_contents
