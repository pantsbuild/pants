# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_counters() -> None:
    result = run_pants(["--stats-counters", "roots"])
    result.assert_success()
    assert "Counters:" in result.stderr
    assert "local_cache_requests: 0" in result.stderr
    assert "remote_cache_requests: 0" in result.stderr
    assert "histogram" not in result.stderr


def test_histograms() -> None:
    # To get the cache read histogram, we must ensure the cache is populated, so we run twice.
    with setup_tmpdir(
        {"src/py/app.py": "print(0)\n", "src/py/BUILD": "python_library()"}
    ) as tmpdir:
        argv = [
            "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black']",
            "--plugins=hdrhistogram",
            "--stats-histograms",
            "lint",
            f"{tmpdir}::",
        ]
        run_pants(argv).assert_success()
        result = run_pants(argv)
    result.assert_success()
    assert "Observation histograms:" in result.stderr
    assert "Histogram for `local_store_read_blob_size`:" in result.stderr
    assert "Counters:" not in result.stderr

    # The option requires `hdrhistogram` be in the global plugins.
    result = run_pants(["--stats-histograms", "roots"])
    result.assert_failure()
    assert "OptionsError" in result.stderr
