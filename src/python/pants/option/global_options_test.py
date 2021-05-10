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
from pants.option.global_options import DynamicRemoteOptions, GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import temporary_dir


def create_dynamic_remote_options(
    *,
    initial_headers: dict[str, str] | None = None,
    address: str | None = "grpc://fake.url:10",
    token_path: str | None = None,
    plugin: str | None = None,
) -> DynamicRemoteOptions:
    if initial_headers is None:
        initial_headers = {}
    args = [
        "--remote-cache-read",
        f"--remote-execution-address={address}",
        f"--remote-store-address={address}",
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
    return DynamicRemoteOptions.from_options(options, env)[0]


def test_dynamic_remote_options_oauth_bearer_token_path() -> None:
    with temporary_dir() as tempdir:
        token_path = Path(tempdir, "token.txt")
        token_path.touch()
        token_path.write_text("my-token")
        opts = create_dynamic_remote_options(
            initial_headers={"foo": "bar"}, token_path=str(token_path)
        )
    assert opts.store_headers == {"authorization": "Bearer my-token", "foo": "bar"}
    assert opts.execution_headers == {
        "authorization": "Bearer my-token",
        "foo": "bar",
    }


def test_dynamic_remote_options_auth_plugin() -> None:
    def compute_options(state: str) -> DynamicRemoteOptions:
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
                            store_address="grpc://custom_store",
                            execution_address="grpc://custom_exec",
                        )
                    """
                )
            )
            sys.path.append(tempdir)
            result = create_dynamic_remote_options(
                initial_headers={"foo": "bar"}, plugin=f"auth_plugin_{state}:auth_func"
            )
            sys.path.pop()
            return result

    opts = compute_options("OK")
    assert opts.store_headers == {
        "store": "abc",
        "foo": "baz",
        "store_url": "grpc://fake.url:10",
    }
    assert opts.execution_headers == {"exec": "xyz", "foo": "baz"}
    assert opts.cache_read is True
    assert opts.instance_name == "custom_instance"
    # Note that the grpc:// prefix will be converted to http://.
    assert opts.store_address == "http://custom_store"
    assert opts.execution_address == "http://custom_exec"

    opts = compute_options("UNAVAILABLE")
    assert opts.cache_read is False
    assert opts.instance_name == "main"


def test_execution_options_remote_addresses() -> None:
    # Test that we properly validate and normalize the scheme.
    host = "fake-with-http-in-url.com:10"
    exec_options = create_dynamic_remote_options(address=f"grpc://{host}")
    assert exec_options.execution_address == f"http://{host}"
    assert exec_options.store_address == f"http://{host}"

    exec_options = create_dynamic_remote_options(address=f"grpcs://{host}")
    assert exec_options.execution_address == f"https://{host}"
    assert exec_options.store_address == f"https://{host}"

    with pytest.raises(ExecutionError):
        create_dynamic_remote_options(address=f"http://{host}")
    with pytest.raises(ExecutionError):
        create_dynamic_remote_options(address=f"https:://{host}")


def test_invalidation_globs() -> None:
    # Confirm that an un-normalized relative path in the pythonpath is filtered out.
    suffix = "something-ridiculous"
    ob = OptionsBootstrapper.create(env={}, args=[f"--pythonpath=../{suffix}"], allow_pantsrc=False)
    globs = GlobalOptions.compute_pantsd_invalidation_globs(
        get_buildroot(), ob.bootstrap_options.for_global_scope()
    )
    for glob in globs:
        assert suffix not in glob
