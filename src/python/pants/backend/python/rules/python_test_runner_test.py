# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.python_test_runner import calculate_timeout_seconds


def test_configured_timeout_greater_than_max():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=10, timeout_default=1, timeout_maximum=2,
        )
        == 2
    )


def test_good_target_timeout():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=2, timeout_default=1, timeout_maximum=10,
        )
        == 2
    )


def test_no_configured_target_timeout():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=None, timeout_default=1, timeout_maximum=2,
        )
        == 1
    )


def test_no_configured_target_timeout_with_bad_default():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=None, timeout_default=10, timeout_maximum=2,
        )
        == 2
    )


def test_no_default_timeout():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=1, timeout_default=None, timeout_maximum=None,
        )
        == 1
    )


def test_no_maximum_timeout():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=1, timeout_default=2, timeout_maximum=None,
        )
        == 1
    )


def test_no_configured_timeouts():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=True, target_timeout=None, timeout_default=None, timeout_maximum=2,
        )
        is None
    )


def test_no_timeouts():
    assert (
        calculate_timeout_seconds(
            timeouts_enabled=False, target_timeout=10, timeout_default=1, timeout_maximum=2,
        )
        is None
    )
