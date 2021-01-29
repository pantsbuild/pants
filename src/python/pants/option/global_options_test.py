# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from textwrap import dedent

from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS, ExecutionOptions
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
            create_option_value_container(**bootstrap_options)  # type: ignore[arg-type]
        )
    assert exec_options.remote_store_headers == {"authorization": "Bearer my-token", "foo": "bar"}
    assert exec_options.remote_execution_headers == {
        "authorization": "Bearer my-token",
        "foo": "bar",
    }


def test_execution_options_auth_plugin() -> None:
    def compute_exec_options(state: str) -> ExecutionOptions:
        with temporary_dir() as tempdir:
            # NB: For an unknown reason, if we use the same file name for multiple runs, the plugin
            # result gets memoized. So, we use a distinct file name.
            plugin_path = Path(tempdir, f"auth_plugin_{state}.py")
            plugin_path.touch()
            plugin_path.write_text(
                dedent(
                    f"""\
                    from pants.option.global_options import AuthPluginState, AuthPluginResult

                    def auth_func(initial_execution_headers, initial_store_headers):
                        return AuthPluginResult(
                            state=AuthPluginState.{state},
                            execution_headers={{
                                **{{k: "baz" for k in initial_execution_headers}},
                                "exec": "xyz",
                            }},
                            store_headers={{
                                **{{k: "baz" for k in initial_store_headers}},
                                "store": "abc",
                            }},
                        )
                    """
                )
            )
            bootstrap_options = {
                **dataclasses.asdict(DEFAULT_EXECUTION_OPTIONS),
                "remote_execution_headers": {"foo": "bar"},
                "remote_store_headers": {"foo": "bar"},
                "remote_oauth_bearer_token_path": None,
                "remote_auth_plugin": f"auth_plugin_{state}:auth_func",
                "remote_execution": True,
            }
            sys.path.append(tempdir)
            result = ExecutionOptions.from_bootstrap_options(
                create_option_value_container(**bootstrap_options)  # type: ignore[arg-type]
            )
            sys.path.pop()
            return result

    exec_options = compute_exec_options("OK")
    assert exec_options.remote_store_headers == {"store": "abc", "foo": "baz"}
    assert exec_options.remote_execution_headers == {"exec": "xyz", "foo": "baz"}
    assert exec_options.remote_execution is True

    exec_options = compute_exec_options("UNAVAILABLE")
    assert exec_options.remote_execution is False
