# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from textwrap import dedent

import pytest

from pants.base.build_environment import get_buildroot
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.unions import UnionMembership
from pants.init.options_initializer import OptionsInitializer
from pants.option.errors import OptionsError
from pants.option.global_options import (
    _REMOTE_ADDRESS_SCHEMES,
    DynamicRemoteOptions,
    GlobalOptions,
    _RemoteAddressScheme,
)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil import rule_runner
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.dirutil import safe_mkdir_for


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
        args.append(f"--backend-packages={plugin}")
    ob = create_options_bootstrapper(args)
    env = CompleteEnvironmentVars({})
    oi = OptionsInitializer(ob, rule_runner.EXECUTOR)
    _build_config = oi.build_config(ob, env)
    options = oi.options(ob, env, _build_config, union_membership=UnionMembership({}), raise_=False)
    return DynamicRemoteOptions.from_options(
        options, env, remote_auth_plugin_func=_build_config.remote_auth_plugin_func
    )[0]


def test_dynamic_remote_options_oauth_bearer_token_path(tmp_path: Path) -> None:
    token_path = tmp_path / "token.txt"
    token_path.touch()
    token_path.write_text("my-token")
    opts = create_dynamic_remote_options(initial_headers={"foo": "bar"}, token_path=str(token_path))
    assert opts.store_headers == {"authorization": "Bearer my-token", "foo": "bar"}
    assert opts.execution_headers == {
        "authorization": "Bearer my-token",
        "foo": "bar",
    }


def test_dynamic_remote_options_auth_plugin(tmp_path: Path) -> None:
    def compute_options(plugin_name: str, state: str) -> DynamicRemoteOptions:
        # NB: If we use the same file name for multiple runs, import loading might be memoized. So
        # we use a distinct file name.
        plugin_path = tmp_path / plugin_name / "register.py"
        safe_mkdir_for(plugin_path)
        plugin_path.touch()
        plugin_path.write_text(
            dedent(
                f"""\
                from pants.option.global_options import AuthPluginState, AuthPluginResult

                def remote_auth(initial_execution_headers, initial_store_headers, options, **kwargs):
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
        sys.path.append(tmp_path.as_posix())
        result = create_dynamic_remote_options(
            initial_headers={"foo": "bar"},
            plugin=plugin_name,
        )
        sys.path.pop()
        return result

    opts = compute_options("ok_plugin", "OK")
    assert opts.store_headers == {
        "store": "abc",
        "foo": "baz",
        "store_url": "grpc://fake.url:10",
    }
    assert opts.execution_headers == {"exec": "xyz", "foo": "baz"}
    assert opts.cache_read is True
    assert opts.cache_write is False
    assert opts.execution is False
    assert opts.instance_name == "custom_instance"
    # Note that the grpc:// prefix will be converted to http://.
    assert opts.store_address == "http://custom_store"
    assert opts.execution_address == "http://custom_exec"

    opts = compute_options("unavailable_plugin", "UNAVAILABLE")
    assert opts.cache_read is False
    assert opts.cache_write is False
    assert opts.execution is False
    assert opts.instance_name is None


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
    # Confirm that an un-normalized relative path in the pythonpath is filtered out, and that an
    # empty entry (i.e.: a relative path for the current directory) doesn't cause an error.
    suffix = "something-ridiculous"
    ob = OptionsBootstrapper.create(
        env={}, args=[f"--pythonpath=../{suffix}", "--pythonpath="], allow_pantsrc=False
    )
    globs = GlobalOptions.compute_pantsd_invalidation_globs(
        get_buildroot(), ob.bootstrap_options.for_global_scope()
    )
    for glob in globs:
        assert suffix not in glob


def _scheme(
    schemes: tuple[str, ...] = ("foo",),
    supports_execution: bool = False,
    experimental: bool = False,
) -> _RemoteAddressScheme:
    return _RemoteAddressScheme(
        schemes=schemes,
        supports_execution=supports_execution,
        experimental=experimental,
        description="DESCRIPTION",
    )


@pytest.mark.parametrize(
    "address",
    [
        "experimental:foo://",
        "experimental:foo://host:123",
        "experimental:foos://path/here",
        "bar://",
        "bar://user@host:123/path?query#fragment",
    ],
)
@pytest.mark.parametrize("execution", [False, True])
def test_remote_schemes_validate_address_should_pass_for_various_good_addresses_without_execution(
    address: str, execution: bool
) -> None:
    _RemoteAddressScheme._validate_address(
        (
            _scheme(schemes=("foo", "foos"), experimental=True, supports_execution=execution),
            # (smoke test require_execution=False supports_execution=True)
            _scheme(schemes=("bar",), supports_execution=True),
        ),
        address,
        require_execution=execution,
        context_for_diagnostics="CONTEXT",
    )


@pytest.mark.parametrize(
    "address",
    ["", "foo", "foo:", "foo:/", "FOO://", "foo:bar://", "fooextra://", "baz://", "bars://"],
)
def test_remote_schemes_validate_address_should_error_when_bad_address(address: str) -> None:
    with pytest.raises(
        OptionsError,
        match=f"(?s)CONTEXT has invalid value `{address}`: it does not have a supported scheme.*start with one of: `foo://`, `foos://`, `bar://`",
    ):
        _RemoteAddressScheme._validate_address(
            (
                _scheme(schemes=("foo", "foos")),
                _scheme(schemes=("bar",)),
            ),
            address,
            require_execution=False,
            context_for_diagnostics="CONTEXT",
        )


def test_remote_schemes_validate_address_should_error_when_missing_experimental() -> None:
    with pytest.raises(
        OptionsError,
        match="(?s)CONTEXT has invalid value `foo://bar`: the scheme `foo` is experimental.*Specify the value as `experimental:foo://bar`",
    ):
        _RemoteAddressScheme._validate_address(
            (_scheme(experimental=True),),
            "foo://bar",
            require_execution=False,
            context_for_diagnostics="CONTEXT",
        )


def test_remote_schemes_validate_address_should_warn_when_unnecessary_experimental(caplog) -> None:
    with caplog.at_level("WARNING"):
        _RemoteAddressScheme._validate_address(
            (_scheme(experimental=False),),
            "experimental:foo://bar",
            require_execution=False,
            context_for_diagnostics="CONTEXT",
        )

    assert "CONTEXT has value `experimental:foo://bar`" in caplog.text
    assert "the scheme `foo` is not experimental" in caplog.text
    assert "Specify the value as `foo://bar`" in caplog.text


def test_remote_schemes_validate_address_should_error_when_execution_required_but_not_supported() -> (
    None
):
    with pytest.raises(
        OptionsError,
        match="(?s)CONTEXT has invalid value `foo://bar`: the scheme `foo` does not support remote execution.*starting with one of: `bar://`",
    ):
        _RemoteAddressScheme._validate_address(
            (
                _scheme(supports_execution=False),
                _scheme(schemes=("bar",), supports_execution=True),
            ),
            "foo://bar",
            require_execution=True,
            context_for_diagnostics="CONTEXT",
        )


def test_remote_schemes_should_have_unique_schemes():
    # the raw schemes supported for remoting (not with experimental: prefix, etc.) should be unique,
    # so there's no accidental ambiguity about, for instance, `http://` configured more than once
    counts = Counter(
        scheme_str for scheme in _REMOTE_ADDRESS_SCHEMES for scheme_str in scheme.schemes
    )
    assert [scheme for scheme, count in counts.items() if count > 1] == []
