# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent
from typing import ContextManager

import pytest

from pants.base.build_environment import get_buildroot
from pants.engine.internals.native_engine import PyRemotingOptions
from pants.engine.internals.scheduler import ExecutionError
from pants.option.bootstrap_options import DynamicRemoteOptions, ExecutionOptions, RemoteProvider
from pants.option.errors import OptionsError
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_dynamic_remote_options
from pants.testutil.pytest_util import no_exception
from pants.util.dirutil import safe_mkdir_for
from pants.version import VERSION


def test_dynamic_remote_options_oauth_bearer_token_with_path(tmp_path: Path) -> None:
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


_DEFAULT_USER_AGENT = f"pants/{VERSION}"


@pytest.mark.parametrize(
    ("input", "expected"),
    [
        ({}, {"user-agent": _DEFAULT_USER_AGENT}),
        ({"user-agent": "same case"}, {"user-agent": "same case"}),
        ({"User-Agent": "title case"}, {"User-Agent": "title case"}),
        ({"not-user-agent": "foo"}, {"user-agent": _DEFAULT_USER_AGENT, "not-user-agent": "foo"}),
    ],
)
def test_execution_options_with_user_agent_should_match_table(
    input: dict[str, str], expected: dict[str, str]
) -> None:
    assert ExecutionOptions.with_user_agent(input) == expected


def test_invalidation_globs() -> None:
    # Confirm that an un-normalized relative path in the pythonpath is filtered out, and that an
    # empty entry (i.e.: a relative path for the current directory) doesn't cause an error.
    suffix = "something-ridiculous"
    ob = OptionsBootstrapper.create(
        args=[f"--pythonpath=../{suffix}", "--pythonpath="], env={}, allow_pantsrc=False
    )
    globs = GlobalOptions.compute_pantsd_invalidation_globs(
        get_buildroot(), ob.bootstrap_options.for_global_scope()
    )
    for glob in globs:
        assert suffix not in glob


@pytest.mark.parametrize(
    ("provider", "address", "expect_raises"),
    [
        (RemoteProvider.reapi, "grpc://example", no_exception()),
        (RemoteProvider.reapi, "grpcs://example", no_exception()),
        (
            RemoteProvider.reapi,
            "http://example",
            pytest.raises(
                OptionsError,
                match=r"(?is)Value `http://example` from ADDRESS is invalid: it doesn't have a scheme that is supported by provider `reapi` from PROVIDER.*Did you mean to use a provider that does support this scheme \(`experimental-github-actions-cache`\) or to use a scheme that is supported by this provider \(`grpc://`, `grpcs://`\)\?",
            ),
        ),
        (
            RemoteProvider.reapi,
            "https://example",
            pytest.raises(
                OptionsError,
                match=r"(?s)Value `https://example` from ADDRESS is invalid.*scheme.*supported",
            ),
        ),
        (
            RemoteProvider.reapi,
            "file://example",
            pytest.raises(
                OptionsError,
                match=r"(?s)Value .* from ADDRESS is invalid.*scheme.*supported.* provider `reapi` from PROVIDER.*Did you mean .* provider .* scheme \(`experimental-file`\) .* provider \(`grpc://`, `grpcs://`\)",
            ),
        ),
        (
            RemoteProvider.reapi,
            "grpc-example",
            pytest.raises(
                OptionsError,
                match=r"(?s)Value .* from ADDRESS is invalid.*scheme.*supported.* provider `reapi` from PROVIDER.*Did you mean to use a scheme that is supported by this provider \(`grpc://`, `grpcs://`\)",
            ),
        ),
        (RemoteProvider.experimental_file, "file://example", no_exception()),
        (
            RemoteProvider.experimental_file,
            "http://example",
            pytest.raises(
                OptionsError,
                match="(?s)Value .* from ADDRESS is invalid.*scheme.*supported",
            ),
        ),
        (RemoteProvider.experimental_github_actions_cache, "http://example", no_exception()),
        (RemoteProvider.experimental_github_actions_cache, "https://example", no_exception()),
        (
            RemoteProvider.experimental_github_actions_cache,
            "file://example",
            pytest.raises(
                OptionsError,
                match="(?si)Value .* from ADDRESS is invalid.*scheme.*supported",
            ),
        ),
    ],
)
def test_remote_provider_validate_address_should_match_table(
    provider: RemoteProvider, address: str, expect_raises: ContextManager
) -> None:
    with expect_raises:
        provider.validate_address(address, address_source="ADDRESS", provider_source="PROVIDER")


@pytest.mark.parametrize(
    ("provider", "expect_raises"),
    [
        (RemoteProvider.reapi, no_exception()),
        (
            RemoteProvider.experimental_file,
            pytest.raises(
                OptionsError,
                match="(?s)Value `experimental-file` from PROVIDER is invalid: it does not support remote execution, but remote execution is required due to IMPLIED BY.*Either disable remote execution, or use a provider that does support remote execution: `reapi`",
            ),
        ),
        (
            RemoteProvider.experimental_github_actions_cache,
            pytest.raises(
                OptionsError,
                match="(?si)Value `experimental-github-actions-cache` from PROVIDER is invalid.*remote execution.*IMPLIED BY",
            ),
        ),
    ],
)
def test_remote_provider_validate_execution_supported_should_match_table(
    provider: RemoteProvider, expect_raises: ContextManager
) -> None:
    with expect_raises:
        provider.validate_execution_supported(
            provider_source="PROVIDER", execution_implied_by="IMPLIED BY"
        )


@pytest.mark.parametrize("provider", RemoteProvider)
def test_remote_provider_matches_rust_enum(
    provider: RemoteProvider,
) -> None:
    PyRemotingOptions(
        # the string should be converted to the Rust-side enum successfully, i.e. Python matches
        # Rust
        provider=provider.value,
        # all the other fields aren't relevant to this test
        execution_enable=False,
        store_headers={},
        store_chunk_bytes=0,
        store_rpc_retries=0,
        store_rpc_concurrency=0,
        store_rpc_timeout_millis=0,
        store_batch_api_size_limit=0,
        store_batch_load_enabled=False,
        cache_warnings_behavior="ignore",
        cache_content_behavior="validate",
        cache_rpc_concurrency=0,
        cache_rpc_timeout_millis=0,
        execution_headers={},
        execution_overall_deadline_secs=0,
        execution_rpc_concurrency=0,
        store_address=None,
        execution_address=None,
        execution_process_cache_namespace=None,
        instance_name=None,
        root_ca_certs_path=None,
        client_certs_path=None,
        client_key_path=None,
        append_only_caches_base_path=None,
    )
