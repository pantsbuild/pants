# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from pathlib import Path

from pants.option.global_options import ExecutionOptions, DEFAULT_EXECUTION_OPTIONS
from pants.testutil.option_util import create_option_value_container
from pants.util.contextutil import temporary_dir


def test_execution_options_remote_oauth_bearer_token_path() -> None:
    with temporary_dir() as tempdir:
        token_path = Path(tempdir, "token.txt")
        token_path.touch()
        token_path.write_text("my-token")
        bootstrap_options = {
            **dataclasses.asdict(DEFAULT_EXECUTION_OPTIONS),
            "remote_execution_headers": {"foo": "bar"},
            "remote_store_headers": {"foo": "bar"},
            "remote_oauth_bearer_token_path": str(token_path),
            "remote_auth_plugin": None,
        }
        exec_options = ExecutionOptions.from_bootstrap_options(
            create_option_value_container(**bootstrap_options)
        )
    assert exec_options.remote_store_headers == {"authorization": "Bearer my-token", "foo": "bar"}
    assert exec_options.remote_execution_headers == {
        "authorization": "Bearer my-token", "foo": "bar"
    }


def test_execution_options_auth_plugin() -> None:
    with temporary_dir() as tempdir:
        plugin_path = Path(tempdir, "plugin.py")
        plugin_path.touch()
        # TODO: write the plugin and figure out how to load it
        plugin_path.write_text("...")
        bootstrap_options = {
            **dataclasses.asdict(DEFAULT_EXECUTION_OPTIONS),
            "remote_execution_headers": {"foo": "bar"},
            "remote_store_headers": {"foo": "bar"},
            "remote_oauth_bearer_token_path": None,
            "remote_auth_plugin": "plugin:auth_func",
        }
        exec_options = ExecutionOptions.from_bootstrap_options(
            create_option_value_container(**bootstrap_options)
        )
    assert exec_options.remote_store_headers == {"store": "abc", "foo": "baz"}
    assert exec_options.remote_execution_headers == {"exec": "xyz", "foo": "baz"}
