# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.goal.anonymous_telemetry import AnonymousTelemetryCallback


@pytest.mark.parametrize(
    "repo_id",
    [
        "a" * 30,
        "2" * 31,
        "C" * 60,
        "c1db8737-06b4-4aa8-b18f-8cde023eb524",
        "D2E39BA4_BA82_4A85_99DC_9E99E4528D3F",
    ],
)
def test_valid_repo_ids(repo_id) -> None:
    assert AnonymousTelemetryCallback.validate_repo_id(repo_id)


@pytest.mark.parametrize(
    "repo_id",
    [
        "",
        "x",
        "a" * 29,
        "2" * 61,
        "@c1db8737-06b4-4aa8-b18f-8cde023eb524",
        "D2E39BA4-BA82-4A85-99DC-9Eá9E4528D3F",
    ],
)
def test_invalid_repo_ids(repo_id) -> None:
    assert not AnonymousTelemetryCallback.validate_repo_id(repo_id)
