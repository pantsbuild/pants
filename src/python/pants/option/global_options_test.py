# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

from pants.base.build_environment import get_buildroot
from pants.engine.environment import CompleteEnvironment
from pants.init.options_initializer import OptionsInitializer
from pants.option.errors import OptionsError
from pants.option.global_options import ExecutionOptions, GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import temporary_dir


def create_execution_options(
    *,
    initial_headers: dict[str, str],
    token_path: str | None = None,
    plugin: str | None = None,
    remote_store_address: str = "grpc://fake.url:10",
    remote_execution_address: str = "grpc://fake.url:10",
    local_only: bool = False,
) -> ExecutionOptions:
    args = [
        "--remote-cache-read",
        f"--remote-execution-address={remote_execution_address}",
        f"--remote-store-address={remote_store_address}",
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
    _build_config, options = OptionsInitializer(ob, env).build_config_and_options(
        ob, env, raise_=False
    )
    return ExecutionOptions.from_options(options, env, local_only=local_only)


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


def test_execution_options_remote_addresses() -> None:
    # Test that we properly validate and normalize the scheme.
    host = "fake-with-http-in-url.com:10"
    exec_options = create_execution_options(
        initial_headers={},
        remote_store_address=f"grpc://{host}",
        remote_execution_address=f"grpc://{host}",
    )
    assert exec_options.remote_execution_address == f"http://{host}"
    assert exec_options.remote_store_address == f"http://{host}"

    exec_options = create_execution_options(
        initial_headers={},
        remote_store_address=f"grpcs://{host}",
        remote_execution_address=f"grpcs://{host}",
    )
    assert exec_options.remote_execution_address == f"https://{host}"
    assert exec_options.remote_store_address == f"https://{host}"

    with pytest.raises(OptionsError):
        create_execution_options(
            initial_headers={},
            remote_store_address=f"http://{host}",
            remote_execution_address=f"grpc://{host}",
        )
    with pytest.raises(OptionsError):
        create_execution_options(
            initial_headers={},
            remote_store_address=f"grpc://{host}",
            remote_execution_address=f"https:://{host}",
        )


def test_execution_options_local_only() -> None:
    # Test that local_only properly disables remote execution. It doesn't need to prune all
    # settings, only those which would trigger usage.
    host = "fake-with-http-in-url.com:10"
    exec_options = create_execution_options(
        initial_headers={},
        remote_store_address=f"grpc://{host}",
        remote_execution_address=f"grpc://{host}",
        local_only=True,
    )
    # Remote execution should be disabled, and the headers should still be empty, indicating that
    # the auth plugin has not run.
    assert not exec_options.remote_execution
    assert not exec_options.remote_cache_read
    assert not exec_options.remote_cache_write
    assert exec_options.remote_store_headers == {}
    assert exec_options.remote_execution_headers == {}


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
            result = create_execution_options(
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


def test_invalidation_globs() -> None:
    # Confirm that an un-normalized relative path in the pythonpath is filtered out.
    suffix = "something-ridiculous"
    ob = OptionsBootstrapper.create(env={}, args=[f"--pythonpath=../{suffix}"], allow_pantsrc=False)
    globs = GlobalOptions.compute_pantsd_invalidation_globs(
        get_buildroot(), ob.bootstrap_options.for_global_scope()
    )
    for glob in globs:
        assert suffix not in glob
