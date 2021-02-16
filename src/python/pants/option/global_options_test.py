# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent
from typing import Dict, Optional

from pants.init.options_initializer import OptionsInitializer
from pants.option.global_options import ExecutionOptions
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import temporary_dir


def create_execution_options(
    *,
    initial_headers: Dict[str, str],
    token_path: Optional[str] = None,
    plugin: Optional[str] = None,
) -> ExecutionOptions:
    args = [
        "--remote-cache-read",
        "--remote-store-server=www.fake.url",
        f"--remote-store-headers={initial_headers}",
        f"--remote-execution-headers={initial_headers}",
        "--remote-instance-name=main",
    ]
    if token_path:
        args.append(f"--remote-oauth-bearer-token-path={token_path}")
    if plugin:
        args.append(f"--remote-auth-plugin={plugin}")
    ob = create_options_bootstrapper(args)
    _build_config, options = OptionsInitializer.create_with_build_config(ob, raise_=False)
    return ExecutionOptions.from_options(options)


def test_execution_options_remote_oauth_bearer_token_path() -> None:
    with temporary_dir() as tempdir:
        token_path = Path(tempdir, "token.txt")
        token_path.touch()
        token_path.write_text("my-token")
        exec_options = create_execution_options(
            initial_headers={"foo": "bar"}, token_path=str(token_path)
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

                    def auth_func(initial_execution_headers, initial_store_headers, options):
                        return AuthPluginResult(
                            state=AuthPluginState.{state},
                            execution_headers={{
                                **{{k: "baz" for k in initial_execution_headers}},
                                "exec": "xyz",
                            }},
                            store_headers={{
                                **{{k: "baz" for k in initial_store_headers}},
                                "store": "abc",
                                "store_url": options.for_global_scope().remote_store_server,
                            }},
                            instance_name="custom_instance",
                        )
                    """
                )
            )
            sys.path.append(tempdir)
            result = create_execution_options(
                initial_headers={"foo": "bar"}, plugin=f"auth_plugin_{state}:auth_func"
            )
            sys.path.pop()
            return result

    exec_options = compute_exec_options("OK")
    assert exec_options.remote_store_headers == {
        "store": "abc",
        "foo": "baz",
        "store_url": ["www.fake.url"],
    }
    assert exec_options.remote_execution_headers == {"exec": "xyz", "foo": "baz"}
    assert exec_options.remote_cache_read is True
    assert exec_options.remote_instance_name == "custom_instance"

    exec_options = compute_exec_options("UNAVAILABLE")
    assert exec_options.remote_cache_read is False
    assert exec_options.remote_instance_name == "main"
