# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import replace
from typing import Any

import pytest

from pants.option.bootstrap_options import DynamicRemoteOptions, RemoteProvider
from pants.option.options_diff import summarize_dynamic_options_diff, summarize_options_map_diff
from pants.testutil.option_util import create_dynamic_remote_options


@pytest.mark.parametrize(
    "old, new, expected_diff",
    [
        [
            {"a": 1, "b": ["x", "y"], "c": True},
            {"a": 1, "b": ["x", "y"], "c": True},
            "",
        ],
        [
            {"l": ["x", "y"]},
            {"l": ["x", "y", "z"]},
            "l: ['x', 'y'] -> ['x', 'y', 'z']",
        ],
        [
            {"flag": True, "a": 30},
            {"flag": False, "a": 30},
            "flag: True -> False",
        ],
        [
            {},
            {"foo": "bar"},
            "foo: None -> 'bar'",
        ],
        [
            {"x": "a", "y": ["b", "c"], "z": True},
            {"x": "d", "y": ["e", "f", "g"], "z": False},
            "x: 'a' -> 'd'; y: ['b', 'c'] -> ['e', 'f', 'g']; z: True -> False",
        ],
        # Sensitive header / token options must not leak plaintext (#23685).
        [
            {"remote_store_headers": {"Authorization": "Bearer OLD"}},
            {"remote_store_headers": {"Authorization": "Bearer NEW"}},
            "remote_store_headers: <redacted> -> <redacted>",
        ],
        [
            {"remote_oauth_bearer_token": "OLD_TOKEN", "parallelism": 4},
            {"remote_oauth_bearer_token": "NEW_TOKEN", "parallelism": 8},
            "parallelism: 4 -> 8; remote_oauth_bearer_token: <redacted> -> <redacted>",
        ],
        [
            {},
            {"remote_execution_headers": {"Authorization": "Bearer SECRET"}},
            "remote_execution_headers: None -> <redacted>",
        ],
    ],
)
def test_summarize_options_map_diff(
    old: dict[str, Any], new: dict[str, Any], expected_diff: str
) -> None:
    diff = summarize_options_map_diff(old, new)
    assert diff == expected_diff


@pytest.mark.parametrize(
    "old, new, expected_diff",
    [
        [
            create_dynamic_remote_options(),
            create_dynamic_remote_options(),
            "",
        ],
        [
            create_dynamic_remote_options(),
            replace(create_dynamic_remote_options(), execution=True),
            "execution: False -> True",
        ],
        [
            create_dynamic_remote_options(),
            replace(create_dynamic_remote_options(), provider=RemoteProvider.experimental_file),
            "provider: 'reapi' -> 'experimental-file'",
        ],
        [
            create_dynamic_remote_options(),
            replace(create_dynamic_remote_options(), store_headers={"auth": "token"}),
            "store_headers: <redacted> -> <redacted>",
        ],
        [
            replace(create_dynamic_remote_options(), execution=True, execution_headers={"x": "1"}),
            replace(create_dynamic_remote_options(), execution=False, execution_headers={}),
            "execution: True -> False; execution_headers: <redacted> -> <redacted>",
        ],
        [
            create_dynamic_remote_options(),
            replace(
                create_dynamic_remote_options(),
                instance_name="test",
                parallelism=32,
            ),
            "instance_name: 'main' -> 'test'; parallelism: 128 -> 32",
        ],
    ],
)
def test_summarize_dynamic_options_diff(
    old: DynamicRemoteOptions, new: DynamicRemoteOptions, expected_diff: str
) -> None:
    diff = summarize_dynamic_options_diff(old, new)
    assert diff == expected_diff
