# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.testutil.pants_integration_test import run_pants

_no_explicit_setting_msg = "An explicit setting will get rid of this message"
_no_repo_id_msg = 'set `repo_id = "<uuid>"` in the [anonymous-telemetry] section of pants.toml'
_bad_repo_id_msg = "must be between 30 and 60 characters long"


def test_warn_if_no_explicit_setting() -> None:
    result = run_pants(["roots"], config={})
    result.assert_success()
    assert _no_explicit_setting_msg in result.stderr
    assert _no_repo_id_msg not in result.stderr
    assert _bad_repo_id_msg not in result.stderr


def test_warn_if_repo_id_unset() -> None:
    result = run_pants(["roots"], config={"anonymous-telemetry": {"enabled": True}})
    result.assert_success()
    assert _no_explicit_setting_msg not in result.stderr
    assert _no_repo_id_msg in result.stderr
    assert _bad_repo_id_msg not in result.stderr


def test_warn_if_repo_id_invalid() -> None:
    result = run_pants(
        ["roots"],
        config={"anonymous-telemetry": {"enabled": True, "repo_id": "tooshort"}},
    )
    result.assert_success()
    assert _no_explicit_setting_msg not in result.stderr
    assert _no_repo_id_msg not in result.stderr
    assert _bad_repo_id_msg in result.stderr


def test_no_warn_if_explicitly_on() -> None:
    result = run_pants(
        ["roots"],
        config={"anonymous-telemetry": {"enabled": True, "repo_id": 36 * "a"}},
    )
    result.assert_success()
    assert _no_explicit_setting_msg not in result.stderr
    assert _no_repo_id_msg not in result.stderr
    assert _bad_repo_id_msg not in result.stderr


def test_no_warn_if_explicitly_off() -> None:
    result = run_pants(["roots"], config={"anonymous-telemetry": {"enabled": False}})
    result.assert_success()
    assert _no_explicit_setting_msg not in result.stderr
    assert _no_repo_id_msg not in result.stderr
    assert _bad_repo_id_msg not in result.stderr
