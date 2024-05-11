# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
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


def test_writing_to_output_file_plain_text() -> None:
    with setup_tmpdir({"src/py/app.py": "print(0)\n", "src/py/BUILD": "python_sources()"}):
        argv1 = [
            "--backend-packages=['pants.backend.python']",
            "--stats-log",
            "--stats-memory-summary",
            "--stats-output-file=stats.txt",
            "roots",
        ]
        run_pants(argv1).assert_success()
        argv2 = [
            "--backend-packages=['pants.backend.python']",
            "--stats-log",
            "--stats-memory-summary",
            "--stats-output-file=stats.txt",
            "list",
            "::",
        ]
        run_pants(argv2).assert_success()
        output_file_contents = Path("stats.txt").read_text()
        for item in ("Counters:", "Memory summary"):
            assert output_file_contents.count(item) == 2

        for item in ("roots", "list"):
            assert item in output_file_contents

        for cmd in (argv1, argv2):
            assert " ".join(cmd) in output_file_contents


def test_writing_to_output_file_json() -> None:
    with setup_tmpdir({"src/py/app.py": "print(0)\n", "src/py/BUILD": "python_sources()"}):
        argv1 = [
            "--backend-packages=['pants.backend.python']",
            "--plugins=hdrhistogram",
            "--stats-log",
            "--stats-memory-summary",
            "--stats-format=jsonlines",
            "--stats-output-file=stats.jsonl",
            "roots",
        ]
        run_pants(argv1).assert_success()
        argv2 = [
            "--backend-packages=['pants.backend.python']",
            "--plugins=hdrhistogram",
            "--stats-log",
            "--stats-memory-summary",
            "--stats-format=jsonlines",
            "--stats-output-file=stats.jsonl",
            "list",
            "::",
        ]
        run_pants(argv2).assert_success()
        stats = []
        with open("stats.jsonl") as fh:
            for line in fh.readlines():
                stats.append(json.loads(line))

        assert len(stats) == 2

        for obj in stats:
            for key in (
                "timestamp",
                "command",
                "counters",
                "memory_summary",
                "observation_histograms",
            ):
                assert obj.get(key) is not None

            for field in ("name", "count"):
                assert obj["counters"][0].get(field) is not None

            for field in ("bytes", "count", "name"):
                assert obj["memory_summary"][0].get(field) is not None
