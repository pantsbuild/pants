# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

from pants.base.build_environment import get_buildroot
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.scheduler import ExecutionError
from pants.init.options_initializer import OptionsInitializer
from pants.option.global_options import (
    DynamicRemoteExecutionOptions,
    ExecutionOptions,
    GlobalOptions,
)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import temporary_dir


def create_dynamic_execution_options(
    *,
    initial_headers: dict[str, str],
    token_path: str | None = None,
    plugin: str | None = None,
    local_only: bool = False,
) -> DynamicRemoteExecutionOptions:
    args = [
        "--remote-cache-read",
        "--remote-execution-address=grpc://fake.url:10",
        "--remote-store-address=grpc://fake.url:10",
        f"--remote-store-headers={initial_headers}",
        f"--remote-execution-headers={initial_headers}",
        "--remote-instance-name=main",
    ]
    if token_path:
        args.append(f"--remote-oauth-bearer-token-path={token_path}")
    if plugin:
        args.append(f"--remote-auth-plugin={plugin}")
    ob = create_options_bootstrapper(args)
    env = CompleteEnvironment({})
    _build_config, options = OptionsInitializer(ob).build_config_and_options(ob, env, raise_=False)
    return DynamicRemoteExecutionOptions.from_options(options, env, local_only=local_only)


def test_dynamic_execution_options_remote_oauth_bearer_token_path() -> None:
    with temporary_dir() as tempdir:
        token_path = Path(tempdir, "token.txt")
        token_path.touch()
        token_path.write_text("my-token")
        exec_options = create_dynamic_execution_options(
            initial_headers={"foo": "bar"}, token_path=str(token_path)
        )
    assert exec_options.remote_store_headers == {"authorization": "Bearer my-token", "foo": "bar"}
    assert exec_options.remote_execution_headers == {
        "authorization": "Bearer my-token",
        "foo": "bar",
    }


def test_dynamic_execution_options_local_only() -> None:
    # Test that local_only properly disables remote execution.
    assert (
        create_dynamic_execution_options(initial_headers={}, local_only=True)
        == DynamicRemoteExecutionOptions.disabled()
    )


def test_dynamic_execution_options_auth_plugin() -> None:
    def compute_exec_options(state: str) -> DynamicRemoteExecutionOptions:
        with temporary_dir() as tempdir:
            # NB: For an unknown reason, if we use the same file name for multiple runs, the plugin
            # result gets memoized. So, we use a distinct file name.
            plugin_path = Path(tempdir, f"auth_plugin_{state}.py")
            plugin_path.touch()
            plugin_path.write_text(
                dedent(
                    f"""\
                    from pants.option.global_options import AuthPluginState, AuthPluginResult

                    def auth_func(initial_execution_headers, initial_store_headers, options, **kwargs):
                        return AuthPluginResult(
                            state=AuthPluginState.{state},
                            execution_headers={{
                                **{{k: "baz" for k in initial_execution_headers}},
                                "exec": "xyz",
                            }},
                            store_headers={{
                                **{{k: "baz" for k in initial_store_headers}},
                                "store": "abc",
                                "store_url": options.for_global_scope().remote_store_address,
                            }},
                            instance_name="custom_instance",
                        )
                    """
                )
            )
            sys.path.append(tempdir)
            result = create_dynamic_execution_options(
                initial_headers={"foo": "bar"}, plugin=f"auth_plugin_{state}:auth_func"
            )
            sys.path.pop()
            return result

    exec_options = compute_exec_options("OK")
    assert exec_options.remote_store_headers == {
        "store": "abc",
        "foo": "baz",
        "store_url": "grpc://fake.url:10",
    }
    assert exec_options.remote_execution_headers == {"exec": "xyz", "foo": "baz"}
    assert exec_options.remote_cache_read is True
    assert exec_options.remote_instance_name == "custom_instance"

    exec_options = compute_exec_options("UNAVAILABLE")
    assert exec_options.remote_cache_read is False
    assert exec_options.remote_instance_name == "main"


def test_execution_options_remote_addresses() -> None:
    # Test that we properly validate and normalize the scheme.

    def create_exec_options(
        remote_store_address: str, remote_execution_address: str
    ) -> ExecutionOptions:
        ob = create_options_bootstrapper(
            [
                f"--remote-store-address={remote_store_address}",
                f"--remote-execution-address={remote_execution_address}",
            ]
        )
        _build_config, options = OptionsInitializer(ob).build_config_and_options(
            ob, CompleteEnvironment({}), raise_=False
        )
        return ExecutionOptions.from_options(
            options.for_global_scope(), DynamicRemoteExecutionOptions.disabled()
        )

    host = "fake-with-http-in-url.com:10"
    exec_options = create_exec_options(f"grpc://{host}", f"grpc://{host}")
    assert exec_options.remote_execution_address == f"http://{host}"
    assert exec_options.remote_store_address == f"http://{host}"

    exec_options = create_exec_options(f"grpcs://{host}", f"grpcs://{host}")
    assert exec_options.remote_execution_address == f"https://{host}"
    assert exec_options.remote_store_address == f"https://{host}"

    with pytest.raises(ExecutionError):
        create_exec_options(f"http://{host}", f"grpc://{host}")
    with pytest.raises(ExecutionError):
        create_exec_options(f"grpc://{host}", f"https:://{host}")


def test_invalidation_globs() -> None:
    # Confirm that an un-normalized relative path in the pythonpath is filtered out.
    suffix = "something-ridiculous"
    ob = OptionsBootstrapper.create(env={}, args=[f"--pythonpath=../{suffix}"], allow_pantsrc=False)
    globs = GlobalOptions.compute_pantsd_invalidation_globs(
        get_buildroot(), ob.bootstrap_options.for_global_scope()
    )
    for glob in globs:
        assert suffix not in glob
