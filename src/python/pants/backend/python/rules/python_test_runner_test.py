# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.python_test_runner import calculate_timeout_seconds


def test_configured_timeout_greater_than_max():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=10,
    timeout_default_seconds=1,
    timeout_maximum_seconds=2,
  ) == 2


def test_good_test_target_timeout():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=2,
    timeout_default_seconds=1,
    timeout_maximum_seconds=10,
  ) == 2


def test_no_configured_test_target_timeout():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=None,
    timeout_default_seconds=1,
    timeout_maximum_seconds=2,
  ) == 1


def test_no_configured_test_target_timeout_with_bad_default():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=None,
    timeout_default_seconds=10,
    timeout_maximum_seconds=2,
  ) == 2


def test_no_default_timeout():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=1,
    timeout_default_seconds=None,
    timeout_maximum_seconds=None,
  ) == 1


def test_no_maximum_timeout():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=1,
    timeout_default_seconds=2,
    timeout_maximum_seconds=None,
  ) == 1


def test_no_configured_timeouts():
  assert calculate_timeout_seconds(
    timeouts=True,
    test_target_timeout_seconds=None,
    timeout_default_seconds=None,
    timeout_maximum_seconds=None,
  ) == None


def test_no_timeouts():
  assert calculate_timeout_seconds(
    timeouts=False,
    test_target_timeout_seconds=10,
    timeout_default_seconds=1,
    timeout_maximum_seconds=2,
  ) == None
