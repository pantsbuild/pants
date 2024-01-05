# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Callable, Type, TypeVar, cast

from pants.base.build_environment import (
    get_buildroot,
    get_default_pants_config_file,
    get_pants_cachedir,
    is_in_container,
    pants_version,
)
from pants.base.deprecated import resolve_conflicting_options
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.fs import FileContent
from pants.engine.internals.native_engine import PyExecutor
from pants.option.custom_types import memory_size
from pants.option.errors import OptionsError
from pants.option.option_types import (
    BoolOption,
    DictOption,
    DirOption,
    EnumOption,
    FloatOption,
    IntOption,
    IntOrStrOption,
    MemorySizeOption,
    StrListOption,
    StrOption,
    collect_options_info,
)
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE
from pants.option.subsystem import Subsystem
from pants.util.dirutil import fast_relpath_optional
from pants.util.docutil import bin_name, doc_url
from pants.util.logging import LogLevel
from pants.util.memo import memoized_classmethod, memoized_property
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.osutil import CPU_COUNT
from pants.util.strutil import Simplifier, fmt_memory_size, softwrap
from pants.version import VERSION

logger = logging.getLogger(__name__)


# The time that leases are acquired for in the local store. Configured on the Python side
# in order to ease interaction with the StoreGCService, which needs to be aware of its value.
LOCAL_STORE_LEASE_TIME_SECS = 2 * 60 * 60


MEGABYTES = 1_000_000
GIGABYTES = 1_000 * MEGABYTES


class DynamicUIRenderer(Enum):
    """Which renderer to use for dyanmic UI."""

    indicatif_spinner = "indicatif-spinner"
    experimental_prodash = "experimental-prodash"


_G = TypeVar("_G", bound="_GlobMatchErrorBehaviorOptionBase")

_EXPERIMENTAL_SCHEME = "experimental:"


def normalize_remote_address(addr: str | None) -> str | None:
    if addr is None:
        return None
    return addr.removeprefix(_EXPERIMENTAL_SCHEME)


@dataclass(frozen=True)
class _RemoteAddressScheme:
    schemes: tuple[str, ...]
    supports_execution: bool
    experimental: bool
    description: str

    def rendered_schemes(self) -> tuple[str, ...]:
        """Convert the schemes into what the user needs to write.

        For example: `experimental:some-scheme://` if experimental, or `some-scheme://` if not.

        This includes the :// because that's clearer in docs etc, even if it's not 'technically'
        part of the scheme.
        """
        # `experimental:` is used as a prefix-scheme, riffing on `view-source:https://...` in some
        # web browsers. This ensures the experimental status is communicated right where a user is
        # opting-in to using it.
        experimental_prefix = _EXPERIMENTAL_SCHEME if self.experimental else ""
        return tuple(f"{experimental_prefix}{scheme}://" for scheme in self.schemes)

    @staticmethod
    def _validate_address(
        schemes: tuple[_RemoteAddressScheme, ...],
        addr: str,
        require_execution: bool,
        context_for_diagnostics: str,
    ) -> None:
        addr_is_experimental = addr.startswith(_EXPERIMENTAL_SCHEME)
        experimentalless_addr = addr.removeprefix(_EXPERIMENTAL_SCHEME)

        matching_scheme = next(
            (
                (scheme_str, scheme)
                for scheme in schemes
                for scheme_str in scheme.schemes
                if experimentalless_addr.startswith(f"{scheme_str}://")
            ),
            None,
        )

        if matching_scheme is None:
            # This an address that doesn't seem to have a scheme we understand.
            supported_schemes = ", ".join(
                f"`{rendered}`" for scheme in schemes for rendered in scheme.rendered_schemes()
            )
            raise OptionsError(
                softwrap(
                    f"""
                    {context_for_diagnostics} has invalid value `{addr}`: it does not have a
                    supported scheme.

                    The value must start with one of: {supported_schemes}
                    """
                )
            )

        scheme_str, scheme = matching_scheme

        if scheme.experimental and not addr_is_experimental:
            # This is a URL like `some-scheme://` for a scheme that IS experimental, so let's tell
            # the user they need to specify it as `experimental:some-scheme://`.
            raise OptionsError(
                softwrap(
                    f"""
                    {context_for_diagnostics} has invalid value `{addr}`: the scheme `{scheme_str}`
                    is experimental and thus must include the `{_EXPERIMENTAL_SCHEME}` prefix to
                    opt-in to this less-stable Pants feature.

                    Specify the value as `{_EXPERIMENTAL_SCHEME}{addr}`, with the
                    `{_EXPERIMENTAL_SCHEME}` prefix.
                    """
                )
            )

        if not scheme.experimental and addr_is_experimental:
            # This is a URL like `experimental:some-scheme://...` for a scheme that's NOT experimental,
            # so let's tell the user to fix it up as `some-scheme://...`. It's low importance (we
            # can unambigiously tell what they mean), so a warning is fine.
            logger.warning(
                softwrap(
                    f"""
                    {context_for_diagnostics} has value `{addr}` including `{_EXPERIMENTAL_SCHEME}`
                    prefix, but the scheme `{scheme_str}` is not experimental.

                    Specify the value as `{experimentalless_addr}`, without the `{_EXPERIMENTAL_SCHEME}`
                    prefix.
                    """
                )
            )

        if require_execution and not scheme.supports_execution:
            # The address is being used for remote execution, but the scheme doesn't support it.
            supported_execution_schemes = ", ".join(
                f"`{rendered}`"
                for scheme in schemes
                if scheme.supports_execution
                for rendered in scheme.rendered_schemes()
            )
            raise OptionsError(
                softwrap(
                    f"""
                    {context_for_diagnostics} has invalid value `{addr}`: the scheme `{scheme_str}`
                    does not support remote execution.

                    Either remove the value (and disable remote execution), or use an address for a
                    server does support remote execution, starting with one of:
                    {supported_execution_schemes} """
                )
            )

        # Validated, all good!

    @staticmethod
    def validate_address(addr: str, require_execution: bool, context_for_diagnostics: str) -> None:
        _RemoteAddressScheme._validate_address(
            _REMOTE_ADDRESS_SCHEMES,
            addr=addr,
            require_execution=require_execution,
            context_for_diagnostics=context_for_diagnostics,
        )

    @staticmethod
    def address_help(context: str, extra: str, requires_execution: bool) -> Callable[[object], str]:
        def render_list_item(scheme_strs: tuple[str, ...], description: str) -> str:
            schemes = ", ".join(f"`{s}`" for s in scheme_strs)
            return f"- {schemes}: {description}"

        def renderer(_: object) -> str:
            supported_schemes = [
                (scheme.rendered_schemes(), scheme.description)
                for scheme in _REMOTE_ADDRESS_SCHEMES
                if not requires_execution or (requires_execution and scheme.supports_execution)
            ]
            if requires_execution:
                # If this is the help for remote execution, still include the schemes that don't
                # support it, but mark them as such.
                supported_schemes.append(
                    (
                        tuple(
                            scheme_str
                            for scheme in _REMOTE_ADDRESS_SCHEMES
                            if not scheme.supports_execution
                            for scheme_str in scheme.rendered_schemes()
                        ),
                        "Remote execution is not supported.",
                    )
                )

            schemes = "\n\n".join(
                render_list_item(scheme_strs, description)
                for scheme_strs, description in supported_schemes
            )
            extra_inline = f"\n\n{extra}" if extra else ""
            return softwrap(
                f"""
                The URI of a server/entity used as a {context}.{extra_inline}

                Supported schemes:

                {schemes}
                """
            )

        return renderer


# This duplicates logic/semantics around choosing a byte store/action cache (and, even, technically,
# remote execution) provider: it'd be nice to have it in one place, but huonw thinks we do the
# validation before starting the engine, and, in any case, we can refactor our way there (the remote
# providers aren't configured in one place yet)
_REMOTE_ADDRESS_SCHEMES = (
    _RemoteAddressScheme(
        schemes=("grpc", "grpcs"),
        supports_execution=True,
        experimental=False,
        description=softwrap(
            """
            Use a [Remote Execution API](https://github.com/bazelbuild/remote-apis) remote
            caching/execution server. `grpcs` uses TLS while `grpc` does not. Format:
            `grpc[s]://$host:$port`.
            """
        ),
    ),
    _RemoteAddressScheme(
        schemes=("file",),
        supports_execution=False,
        experimental=True,
        description=softwrap(
            """
            Use a local directory as a 'remote' store, for testing, debugging, or potentially an NFS
            mount. Format: `file://$path`. For example: `file:///tmp/remote-cache-example/` will
            store within the `/tmp/remote-cache-example/` directory, creating it if necessary.
            """
        ),
    ),
    _RemoteAddressScheme(
        schemes=("github-actions-cache+http", "github-actions-cache+https"),
        supports_execution=False,
        experimental=True,
        description=softwrap(
            f"""
            Use the GitHub Actions Cache for fine-grained caching. This requires extracting
            `ACTIONS_CACHE_URL` (passing it in `PANTS_REMOTE_STORE_ADDRESS`) and
            `ACTIONS_RUNTIME_TOKEN` (passing it in `PANTS_REMOTE_OAUTH_BEARER_TOKEN`). See
            {doc_url('remote-caching#github-actions-cache')} for more details.
            """
        ),
    ),
)


@dataclass(frozen=True)
class _GlobMatchErrorBehaviorOptionBase:
    """This class exists to have dedicated types per global option of the `GlobMatchErrorBehavior`
    so we can extract the relevant option in a rule to limit the scope of downstream rules to avoid
    depending on the entire global options data."""

    error_behavior: GlobMatchErrorBehavior

    @classmethod
    def ignore(cls: type[_G]) -> _G:
        return cls(GlobMatchErrorBehavior.ignore)

    @classmethod
    def warn(cls: type[_G]) -> _G:
        return cls(GlobMatchErrorBehavior.warn)

    @classmethod
    def error(cls: type[_G]) -> _G:
        return cls(GlobMatchErrorBehavior.error)


class UnmatchedBuildFileGlobs(_GlobMatchErrorBehaviorOptionBase):
    """What to do when globs do not match in BUILD files."""


class UnmatchedCliGlobs(_GlobMatchErrorBehaviorOptionBase):
    """What to do when globs do not match in CLI args."""


class OwnersNotFoundBehavior(_GlobMatchErrorBehaviorOptionBase):
    """What to do when a file argument cannot be mapped to an owning target."""


@enum.unique
class RemoteCacheWarningsBehavior(Enum):
    ignore = "ignore"
    first_only = "first_only"
    backoff = "backoff"
    always = "always"


@enum.unique
class CacheContentBehavior(Enum):
    fetch = "fetch"
    validate = "validate"
    defer = "defer"


class KeepSandboxes(Enum):
    """An enum for the global option `keep_sandboxes`.

    Prefer to use this rather than requesting `GlobalOptions` for more precise invalidation.
    """

    always = "always"
    on_failure = "on_failure"
    never = "never"


@enum.unique
class AuthPluginState(Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AuthPluginResult:
    """The return type for a function specified via `[GLOBAL].remote_auth_plugin`.

    The returned `store_headers` and `execution_headers` will replace whatever headers Pants would
    have used normally, e.g. what is set with `[GLOBAL].remote_store_headers`. This allows you to control
    the merge strategy if your plugin sets conflicting headers. Usually, you will want to preserve
    the `initial_store_headers` and `initial_execution_headers` passed to the plugin.

    If set, the returned `instance_name` will override `[GLOBAL].remote_instance_name`,
    `store_address` will override `[GLOBAL].remote_store_address`, and `execution_address` will
    override ``[GLOBAL].remote_execution_address``. The addresses are interpreted and validated in
    the same manner as the corresponding option.
    """

    state: AuthPluginState
    store_headers: dict[str, str]
    execution_headers: dict[str, str]
    store_address: str | None = None
    execution_address: str | None = None
    instance_name: str | None = None
    expiration: datetime | None = None
    plugin_name: str | None = None

    def __post_init__(self) -> None:
        name = self.plugin_name or ""
        plugin_context = f"in `AuthPluginResult` returned from `[GLOBAL].remote_auth_plugin` {name}"

        if self.store_address:
            _RemoteAddressScheme.validate_address(
                self.store_address,
                require_execution=False,
                context_for_diagnostics=f"`store_address` {plugin_context}",
            )
        if self.execution_address:
            _RemoteAddressScheme.validate_address(
                self.execution_address,
                require_execution=True,
                context_for_diagnostics=f"`execution_address` {plugin_context}",
            )

    @property
    def is_available(self) -> bool:
        return self.state == AuthPluginState.OK


@dataclass(frozen=True)
class DynamicRemoteOptions:
    """Options related to remote execution of processes which are computed dynamically."""

    execution: bool
    cache_read: bool
    cache_write: bool
    instance_name: str | None
    store_address: str | None
    execution_address: str | None
    store_headers: dict[str, str]
    execution_headers: dict[str, str]
    parallelism: int
    store_rpc_concurrency: int
    cache_rpc_concurrency: int
    execution_rpc_concurrency: int

    def _validate_store_addr(self) -> None:
        if self.store_address:
            return
        if self.cache_read:
            raise OptionsError(
                softwrap(
                    """
                    The `[GLOBAL].remote_cache_read` option requires also setting the
                    `[GLOBAL].remote_store_address` option in order to work properly.
                    """
                )
            )
        if self.cache_write:
            raise OptionsError(
                softwrap(
                    """
                    The `[GLOBAL].remote_cache_write` option requires also setting the
                    `[GLOBAL].remote_store_address` option in order to work properly.
                    """
                )
            )

    def _validate_exec_addr(self) -> None:
        if not self.execution:
            return
        if not self.execution_address:
            raise OptionsError(
                softwrap(
                    """
                    The `[GLOBAL].remote_execution` option requires also setting the
                    `[GLOBAL].remote_execution_address` option in order to work properly.
                    """
                )
            )
        if not self.store_address:
            raise OptionsError(
                softwrap(
                    """
                    The `[GLOBAL].remote_execution_address` option requires also setting the
                    `[GLOBAL].remote_store_address` option. Often these have the same value.
                    """
                )
            )

    def __post_init__(self) -> None:
        self._validate_store_addr()
        self._validate_exec_addr()

    @classmethod
    def disabled(cls) -> DynamicRemoteOptions:
        return cls(
            execution=False,
            cache_read=False,
            cache_write=False,
            instance_name=None,
            store_address=None,
            execution_address=None,
            store_headers={},
            execution_headers={},
            parallelism=DEFAULT_EXECUTION_OPTIONS.process_execution_remote_parallelism,
            store_rpc_concurrency=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_concurrency,
            cache_rpc_concurrency=DEFAULT_EXECUTION_OPTIONS.remote_cache_rpc_concurrency,
            execution_rpc_concurrency=DEFAULT_EXECUTION_OPTIONS.remote_execution_rpc_concurrency,
        )

    @classmethod
    def _use_oauth_token(cls, bootstrap_options: OptionValueContainer) -> DynamicRemoteOptions:
        if bootstrap_options.remote_oauth_bearer_token:
            oauth_token = bootstrap_options.remote_oauth_bearer_token
            description = "`remote_oauth_bearer_token` option"
        else:
            oauth_token = (
                Path(bootstrap_options.remote_oauth_bearer_token_path).resolve().read_text().strip()
            )
            description = f"`remote_oauth_bearer_token_path` option ({bootstrap_options.remote_oauth_bearer_token_path})"

        if set(oauth_token).intersection({"\n", "\r"}):
            raise OptionsError(
                f"OAuth bearer token from {description} must not contain multiple lines."
            )

        token_header = {"authorization": f"Bearer {oauth_token}"}
        execution = cast(bool, bootstrap_options.remote_execution)
        cache_read = cast(bool, bootstrap_options.remote_cache_read)
        cache_write = cast(bool, bootstrap_options.remote_cache_write)
        store_address = cast("str | None", bootstrap_options.remote_store_address)
        execution_address = cast("str | None", bootstrap_options.remote_execution_address)
        instance_name = cast("str | None", bootstrap_options.remote_instance_name)
        execution_headers = cast("dict[str, str]", bootstrap_options.remote_execution_headers)
        store_headers = cast("dict[str, str]", bootstrap_options.remote_store_headers)
        parallelism = cast(int, bootstrap_options.process_execution_remote_parallelism)
        store_rpc_concurrency = cast(int, bootstrap_options.remote_store_rpc_concurrency)
        cache_rpc_concurrency = cast(int, bootstrap_options.remote_cache_rpc_concurrency)
        execution_rpc_concurrency = cast(int, bootstrap_options.remote_execution_rpc_concurrency)
        execution_headers.update(token_header)
        store_headers.update(token_header)
        return cls(
            execution=execution,
            cache_read=cache_read,
            cache_write=cache_write,
            instance_name=instance_name,
            store_address=cls._normalize_address(store_address),
            execution_address=cls._normalize_address(execution_address),
            store_headers=store_headers,
            execution_headers=execution_headers,
            parallelism=parallelism,
            store_rpc_concurrency=store_rpc_concurrency,
            cache_rpc_concurrency=cache_rpc_concurrency,
            execution_rpc_concurrency=execution_rpc_concurrency,
        )

    @classmethod
    def from_options(
        cls,
        full_options: Options,
        env: CompleteEnvironmentVars,
        prior_result: AuthPluginResult | None = None,
        remote_auth_plugin_func: Callable | None = None,
    ) -> tuple[DynamicRemoteOptions, AuthPluginResult | None]:
        bootstrap_options = full_options.bootstrap_option_values()
        assert bootstrap_options is not None
        execution = cast(bool, bootstrap_options.remote_execution)
        cache_read = cast(bool, bootstrap_options.remote_cache_read)
        cache_write = cast(bool, bootstrap_options.remote_cache_write)
        if not (execution or cache_read or cache_write):
            return cls.disabled(), None

        sources = {
            str(remote_auth_plugin_func): bool(remote_auth_plugin_func),
            "[GLOBAL].remote_oauth_bearer_token_path": bool(
                bootstrap_options.remote_oauth_bearer_token_path
            ),
            "[GLOBAL].remote_oauth_bearer_token": bool(bootstrap_options.remote_oauth_bearer_token),
        }
        enabled_sources = [name for name, enabled in sources.items() if enabled]
        if len(enabled_sources) > 1:
            rendered = ", ".join(f"`{name}`" for name in enabled_sources)
            raise OptionsError(
                softwrap(
                    f"""
                    Multiple options are set that provide auth information: {rendered}.
                    This is not supported. Only one of those should be set.
                    """
                )
            )
        if (
            bootstrap_options.remote_oauth_bearer_token_path
            or bootstrap_options.remote_oauth_bearer_token
        ):
            return cls._use_oauth_token(bootstrap_options), None
        if remote_auth_plugin_func is not None:
            return cls._use_auth_plugin(
                bootstrap_options,
                full_options=full_options,
                env=env,
                prior_result=prior_result,
                remote_auth_plugin_func=remote_auth_plugin_func,
            )
        return cls._use_no_auth(bootstrap_options), None

    @classmethod
    def _use_no_auth(cls, bootstrap_options: OptionValueContainer) -> DynamicRemoteOptions:
        execution = cast(bool, bootstrap_options.remote_execution)
        cache_read = cast(bool, bootstrap_options.remote_cache_read)
        cache_write = cast(bool, bootstrap_options.remote_cache_write)
        store_address = cast("str | None", bootstrap_options.remote_store_address)
        execution_address = cast("str | None", bootstrap_options.remote_execution_address)
        instance_name = cast("str | None", bootstrap_options.remote_instance_name)
        execution_headers = cast("dict[str, str]", bootstrap_options.remote_execution_headers)
        store_headers = cast("dict[str, str]", bootstrap_options.remote_store_headers)
        parallelism = cast(int, bootstrap_options.process_execution_remote_parallelism)
        store_rpc_concurrency = cast(int, bootstrap_options.remote_store_rpc_concurrency)
        cache_rpc_concurrency = cast(int, bootstrap_options.remote_cache_rpc_concurrency)
        execution_rpc_concurrency = cast(int, bootstrap_options.remote_execution_rpc_concurrency)
        return cls(
            execution=execution,
            cache_read=cache_read,
            cache_write=cache_write,
            instance_name=instance_name,
            store_address=cls._normalize_address(store_address),
            execution_address=cls._normalize_address(execution_address),
            store_headers=store_headers,
            execution_headers=execution_headers,
            parallelism=parallelism,
            store_rpc_concurrency=store_rpc_concurrency,
            cache_rpc_concurrency=cache_rpc_concurrency,
            execution_rpc_concurrency=execution_rpc_concurrency,
        )

    @classmethod
    def _use_auth_plugin(
        cls,
        bootstrap_options: OptionValueContainer,
        full_options: Options,
        env: CompleteEnvironmentVars,
        prior_result: AuthPluginResult | None,
        remote_auth_plugin_func: Callable,
    ) -> tuple[DynamicRemoteOptions, AuthPluginResult | None]:
        execution = cast(bool, bootstrap_options.remote_execution)
        cache_read = cast(bool, bootstrap_options.remote_cache_read)
        cache_write = cast(bool, bootstrap_options.remote_cache_write)
        store_address = cast("str | None", bootstrap_options.remote_store_address)
        execution_address = cast("str | None", bootstrap_options.remote_execution_address)
        instance_name = cast("str | None", bootstrap_options.remote_instance_name)
        execution_headers = cast("dict[str, str]", bootstrap_options.remote_execution_headers)
        store_headers = cast("dict[str, str]", bootstrap_options.remote_store_headers)
        parallelism = cast(int, bootstrap_options.process_execution_remote_parallelism)
        store_rpc_concurrency = cast(int, bootstrap_options.remote_store_rpc_concurrency)
        cache_rpc_concurrency = cast(int, bootstrap_options.remote_cache_rpc_concurrency)
        execution_rpc_concurrency = cast(int, bootstrap_options.remote_execution_rpc_concurrency)
        auth_plugin_result = cast(
            AuthPluginResult,
            remote_auth_plugin_func(
                initial_execution_headers=execution_headers,
                initial_store_headers=store_headers,
                options=full_options,
                env=dict(env),
                prior_result=prior_result,
            ),
        )
        plugin_name = (
            auth_plugin_result.plugin_name
            or f"{remote_auth_plugin_func.__module__}.{remote_auth_plugin_func.__name__}"
        )
        if not auth_plugin_result.is_available:
            # NB: This is debug because we expect plugins to log more informative messages.
            logger.debug(
                f"Disabling remote caching and remote execution because authentication was not available via the plugin {plugin_name} (from `[GLOBAL].remote_auth_plugin`)."
            )
            return cls.disabled(), None

        logger.debug(
            f"Remote auth plugin `{plugin_name}` succeeded. Remote caching/execution will be attempted."
        )
        execution_headers = auth_plugin_result.execution_headers
        store_headers = auth_plugin_result.store_headers
        plugin_provided_opt_log = "Setting `[GLOBAL].remote_{opt}` is not needed and will be ignored since it is provided by the auth plugin: {plugin_name}."
        if auth_plugin_result.instance_name is not None:
            if instance_name is not None:
                logger.warning(
                    plugin_provided_opt_log.format(opt="instance_name", plugin_name=plugin_name)
                )
            instance_name = auth_plugin_result.instance_name
        if auth_plugin_result.store_address is not None:
            if store_address is not None:
                logger.warning(
                    plugin_provided_opt_log.format(opt="store_address", plugin_name=plugin_name)
                )
            store_address = auth_plugin_result.store_address
        if auth_plugin_result.execution_address is not None:
            if execution_address is not None:
                logger.warning(
                    plugin_provided_opt_log.format(opt="execution_address", plugin_name=plugin_name)
                )
            execution_address = auth_plugin_result.execution_address

        opts = cls(
            execution=execution,
            cache_read=cache_read,
            cache_write=cache_write,
            instance_name=instance_name,
            store_address=cls._normalize_address(store_address),
            execution_address=cls._normalize_address(execution_address),
            store_headers=store_headers,
            execution_headers=execution_headers,
            parallelism=parallelism,
            store_rpc_concurrency=store_rpc_concurrency,
            cache_rpc_concurrency=cache_rpc_concurrency,
            execution_rpc_concurrency=execution_rpc_concurrency,
        )
        return opts, auth_plugin_result

    @classmethod
    def _normalize_address(cls, address: str | None) -> str | None:
        # NB: Tonic expects the schemes `http` and `https`, even though they are gRPC requests.
        # We validate that users set `grpc` and `grpcs` in the options system / plugin for clarity,
        # but then normalize to `http`/`https`.
        # TODO: move this logic into the actual remote providers
        return re.sub(r"^grpc", "http", address) if address else None


@dataclass(frozen=True)
class ExecutionOptions:
    """A collection of all options related to (remote) execution of processes.

    TODO: These options should move to a Subsystem once we add support for "bootstrap" Subsystems (ie,
    allowing Subsystems to be consumed before the Scheduler has been created).
    """

    remote_execution: bool
    remote_cache_read: bool
    remote_cache_write: bool

    remote_instance_name: str | None
    remote_ca_certs_path: str | None
    remote_client_certs_path: str | None
    remote_client_key_path: str | None

    keep_sandboxes: KeepSandboxes
    local_cache: bool
    process_execution_local_parallelism: int
    process_execution_local_enable_nailgun: bool
    process_execution_remote_parallelism: int
    process_execution_cache_namespace: str | None
    process_execution_graceful_shutdown_timeout: int
    cache_content_behavior: CacheContentBehavior

    process_total_child_memory_usage: int | None
    process_per_child_memory_usage: int

    remote_store_address: str | None
    remote_store_headers: dict[str, str]
    remote_store_chunk_bytes: Any
    remote_store_rpc_retries: int
    remote_store_rpc_concurrency: int
    remote_store_batch_api_size_limit: int
    remote_store_rpc_timeout_millis: int

    remote_cache_warnings: RemoteCacheWarningsBehavior
    remote_cache_rpc_concurrency: int
    remote_cache_rpc_timeout_millis: int

    remote_execution_address: str | None
    remote_execution_headers: dict[str, str]
    remote_execution_overall_deadline_secs: int
    remote_execution_rpc_concurrency: int

    remote_execution_append_only_caches_base_path: str | None

    @classmethod
    def from_options(
        cls,
        bootstrap_options: OptionValueContainer,
        dynamic_remote_options: DynamicRemoteOptions,
    ) -> ExecutionOptions:
        return cls(
            # Remote execution strategy.
            remote_execution=dynamic_remote_options.execution,
            remote_cache_read=dynamic_remote_options.cache_read,
            remote_cache_write=dynamic_remote_options.cache_write,
            # General remote setup.
            remote_instance_name=dynamic_remote_options.instance_name,
            remote_ca_certs_path=bootstrap_options.remote_ca_certs_path,
            remote_client_certs_path=bootstrap_options.remote_client_certs_path,
            remote_client_key_path=bootstrap_options.remote_client_key_path,
            # Process execution setup.
            keep_sandboxes=GlobalOptions.resolve_keep_sandboxes(bootstrap_options),
            local_cache=bootstrap_options.local_cache,
            process_execution_local_parallelism=bootstrap_options.process_execution_local_parallelism,
            process_execution_remote_parallelism=dynamic_remote_options.parallelism,
            process_execution_cache_namespace=bootstrap_options.process_execution_cache_namespace,
            process_execution_graceful_shutdown_timeout=bootstrap_options.process_execution_graceful_shutdown_timeout,
            process_execution_local_enable_nailgun=bootstrap_options.process_execution_local_enable_nailgun,
            cache_content_behavior=bootstrap_options.cache_content_behavior,
            process_total_child_memory_usage=bootstrap_options.process_total_child_memory_usage,
            process_per_child_memory_usage=bootstrap_options.process_per_child_memory_usage,
            # Remote store setup.
            remote_store_address=dynamic_remote_options.store_address,
            remote_store_headers=dynamic_remote_options.store_headers,
            remote_store_chunk_bytes=bootstrap_options.remote_store_chunk_bytes,
            remote_store_rpc_retries=bootstrap_options.remote_store_rpc_retries,
            remote_store_rpc_concurrency=dynamic_remote_options.store_rpc_concurrency,
            remote_store_batch_api_size_limit=bootstrap_options.remote_store_batch_api_size_limit,
            remote_store_rpc_timeout_millis=bootstrap_options.remote_store_rpc_timeout_millis,
            # Remote cache setup.
            remote_cache_warnings=bootstrap_options.remote_cache_warnings,
            remote_cache_rpc_concurrency=dynamic_remote_options.cache_rpc_concurrency,
            remote_cache_rpc_timeout_millis=bootstrap_options.remote_cache_rpc_timeout_millis,
            # Remote execution setup.
            remote_execution_address=dynamic_remote_options.execution_address,
            remote_execution_headers=dynamic_remote_options.execution_headers,
            remote_execution_overall_deadline_secs=bootstrap_options.remote_execution_overall_deadline_secs,
            remote_execution_rpc_concurrency=dynamic_remote_options.execution_rpc_concurrency,
            remote_execution_append_only_caches_base_path=bootstrap_options.remote_execution_append_only_caches_base_path,
        )


@dataclass(frozen=True)
class LocalStoreOptions:
    """A collection of all options related to the local store.

    TODO: These options should move to a Subsystem once we add support for "bootstrap" Subsystems (ie,
    allowing Subsystems to be consumed before the Scheduler has been created).
    """

    store_dir: str = os.path.join(get_pants_cachedir(), "lmdb_store")
    processes_max_size_bytes: int = 16 * GIGABYTES
    files_max_size_bytes: int = 256 * GIGABYTES
    directories_max_size_bytes: int = 16 * GIGABYTES
    shard_count: int = 16

    def target_total_size_bytes(self) -> int:
        """Returns the target total size of all of the stores.

        The `max_size` values are caps on the total size of each store: the "target" size
        is the size that garbage collection will attempt to shrink the stores to each time
        it runs.

        NB: This value is not currently configurable, but that could be desirable in the future.
        """
        max_total_size_bytes = (
            self.processes_max_size_bytes
            + self.files_max_size_bytes
            + self.directories_max_size_bytes
        )
        return max_total_size_bytes // 10

    @classmethod
    def from_options(cls, options: OptionValueContainer) -> LocalStoreOptions:
        return cls(
            store_dir=str(Path(options.local_store_dir).resolve()),
            processes_max_size_bytes=options.local_store_processes_max_size_bytes,
            files_max_size_bytes=options.local_store_files_max_size_bytes,
            directories_max_size_bytes=options.local_store_directories_max_size_bytes,
            shard_count=options.local_store_shard_count,
        )


_PER_CHILD_MEMORY_USAGE = "512MiB"


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions(
    # Remote execution strategy.
    remote_execution=False,
    remote_cache_read=False,
    remote_cache_write=False,
    # General remote setup.
    remote_instance_name=None,
    remote_ca_certs_path=None,
    remote_client_certs_path=None,
    remote_client_key_path=None,
    # Process execution setup.
    process_total_child_memory_usage=None,
    process_per_child_memory_usage=memory_size(_PER_CHILD_MEMORY_USAGE),
    process_execution_local_parallelism=CPU_COUNT,
    process_execution_remote_parallelism=128,
    process_execution_cache_namespace=None,
    keep_sandboxes=KeepSandboxes.never,
    local_cache=True,
    cache_content_behavior=CacheContentBehavior.fetch,
    process_execution_local_enable_nailgun=True,
    process_execution_graceful_shutdown_timeout=3,
    # Remote store setup.
    remote_store_address=None,
    remote_store_headers={
        "user-agent": f"pants/{VERSION}",
    },
    remote_store_chunk_bytes=1024 * 1024,
    remote_store_rpc_retries=2,
    remote_store_rpc_concurrency=128,
    remote_store_batch_api_size_limit=4194304,
    remote_store_rpc_timeout_millis=30000,
    # Remote cache setup.
    remote_cache_warnings=RemoteCacheWarningsBehavior.backoff,
    remote_cache_rpc_concurrency=128,
    remote_cache_rpc_timeout_millis=1500,
    # Remote execution setup.
    remote_execution_address=None,
    remote_execution_headers={
        "user-agent": f"pants/{VERSION}",
    },
    remote_execution_overall_deadline_secs=60 * 60,  # one hour
    remote_execution_rpc_concurrency=128,
    remote_execution_append_only_caches_base_path=None,
)

DEFAULT_LOCAL_STORE_OPTIONS = LocalStoreOptions()


class LogLevelOption(EnumOption[LogLevel, LogLevel]):
    """The `--level` option.

    This is a dedicated class because it's the only option where we allow both the short flag `-l`
    and the long flag `--level`.
    """

    def __new__(cls) -> LogLevelOption:
        self = super().__new__(
            cls,  # type: ignore[arg-type]
            default=LogLevel.INFO,
            daemon=True,
            help="Set the logging level.",
        )
        self._flag_names = ("-l", "--level")
        return self  # type: ignore[return-value]


class BootstrapOptions:
    """The set of options necessary to create a Scheduler.

    If an option is not consumed during creation of a Scheduler, it should be a property of
    GlobalOptions instead. Either way these options are injected into the GlobalOptions, which is
    how they should be accessed (as normal global-scope options).

    Their status as "bootstrap options" is only pertinent during option registration.
    """

    _default_distdir_name = "dist"
    _default_rel_distdir = f"/{_default_distdir_name}/"

    backend_packages = StrListOption(
        advanced=True,
        help=softwrap(
            """
            Register functionality from these backends.

            The backend packages must be present on the PYTHONPATH, typically because they are in
            the Pants core dist, in a plugin dist, or available as sources in the repo.
            """
        ),
    )
    plugins = StrListOption(
        advanced=True,
        help=softwrap(
            """
            Allow backends to be loaded from these plugins (usually released through PyPI).
            The default backends for each plugin will be loaded automatically. Other backends
            in a plugin can be loaded by listing them in `backend_packages` in the
            `[GLOBAL]` scope.
            """
        ),
    )
    plugins_force_resolve = BoolOption(
        advanced=True,
        default=False,
        help="Re-resolve plugins, even if previously resolved.",
    )
    level = LogLevelOption()
    show_log_target = BoolOption(
        default=False,
        daemon=True,
        advanced=True,
        help=softwrap(
            """
            Display the target where a log message originates in that log message's output.
            This can be helpful when paired with `--log-levels-by-target`.
            """
        ),
    )
    log_levels_by_target = DictOption[str](
        # TODO: While we would like this option to be fingerprinted for the daemon, the Rust side
        # option parser does not support dict options. See #19832.
        # daemon=True,
        advanced=True,
        help=softwrap(
            """
            Set a more specific logging level for one or more logging targets. The names of
            logging targets are specified in log strings when the --show-log-target option is set.
            The logging levels are one of: "error", "warn", "info", "debug", "trace".
            All logging targets not specified here use the global log level set with `--level`. For example,
            you can set `--log-levels-by-target='{"workunit_store": "info", "pants.engine.rules": "warn"}'`.
            """
        ),
    )
    log_show_rust_3rdparty = BoolOption(
        default=False,
        daemon=True,
        advanced=True,
        help="Whether to show/hide logging done by 3rdparty Rust crates used by the Pants engine.",
    )
    ignore_warnings = StrListOption(
        daemon=True,
        advanced=True,
        help=softwrap(
            """
            Ignore logs and warnings matching these strings.

            Normally, Pants will look for literal matches from the start of the log/warning
            message, but you can prefix the ignore with `$regex$` for Pants to instead treat
            your string as a regex pattern. For example:

                ignore_warnings = [
                    "DEPRECATED: option 'config' in scope 'flake8' will be removed",
                    '$regex$:No files\\s*'
                ]
            """
        ),
    )
    pants_version = StrOption(
        advanced=True,
        default=pants_version(),
        default_help_repr="<pants_version>",
        daemon=True,
        help=softwrap(
            f"""
            Use this Pants version. Note that Pants only uses this to verify that you are
            using the requested version, as Pants cannot dynamically change the version it
            is using once the program is already running.

            If you use the `{bin_name()}` script from {doc_url('installation')}, however, changing
            the value in your `pants.toml` will cause the new version to be installed and run automatically.

            Run `{bin_name()} --version` to check what is being used.
            """
        ),
    )
    pants_bin_name = StrOption(
        advanced=True,
        default="pants",  # noqa: PANTSBIN
        help=softwrap(
            """
            The name of the script or binary used to invoke Pants.
            Useful when printing help messages.
            """
        ),
    )
    pants_workdir = StrOption(
        advanced=True,
        metavar="<dir>",
        default=lambda _: os.path.join(get_buildroot(), ".pants.d", "workdir"),
        daemon=True,
        help="Write intermediate logs and output files to this dir.",
    )
    pants_physical_workdir_base = StrOption(
        advanced=True,
        metavar="<dir>",
        default=None,
        daemon=True,
        help=softwrap(
            """
            When set, a base directory in which to store `--pants-workdir` contents.
            If this option is a set, the workdir will be created as symlink into a
            per-workspace subdirectory.
            """
        ),
    )
    pants_distdir = StrOption(
        advanced=True,
        metavar="<dir>",
        default=lambda _: os.path.join(get_buildroot(), "dist"),
        help="Write end products, such as the results of `pants package`, to this dir.",  # noqa: PANTSBIN
    )
    pants_subprocessdir = StrOption(
        advanced=True,
        default=lambda _: os.path.join(get_buildroot(), ".pants.d", "pids"),
        daemon=True,
        help=softwrap(
            """
            The directory to use for tracking subprocess metadata. This should
            live outside of the dir used by `pants_workdir` to allow for tracking
            subprocesses that outlive the workdir data.
            """
        ),
    )
    pants_config_files = StrListOption(
        advanced=True,
        # NB: We don't fingerprint the list of config files, because the content of the config
        # files independently affects fingerprints.
        fingerprint=False,
        default=lambda _: [get_default_pants_config_file()],
        help=softwrap(
            """
            Paths to Pants config files. This may only be set through the environment variable
            `PANTS_CONFIG_FILES` and the command line argument `--pants-config-files`; it will
            be ignored if in a config file like `pants.toml`.
            """
        ),
    )
    pantsrc = BoolOption(
        advanced=True,
        default=True,
        # NB: See `--pants-config-files`.
        fingerprint=False,
        help="Use pantsrc files located at the paths specified in the global option `pantsrc_files`.",
    )
    pantsrc_files = StrListOption(
        advanced=True,
        metavar="<path>",
        # NB: See `--pants-config-files`.
        fingerprint=False,
        default=["/etc/pantsrc", "~/.pants.rc", ".pants.rc"],
        help="Override config with values from these files, using syntax matching that of `--pants-config-files`.",
    )
    pythonpath = StrListOption(
        advanced=True,
        help=softwrap(
            """
            Add these directories to PYTHONPATH to search for plugins. This does not impact the
            PYTHONPATH used by Pants when running your Python code.
            """
        ),
    )
    spec_files = StrListOption(
        # NB: We don't fingerprint spec files because the content of the files independently
        # affects fingerprints.
        fingerprint=False,
        help=softwrap(
            """
            Read additional specs (target addresses, files, and/or globs), one per line, from these
            files.
            """
        ),
    )
    verify_config = BoolOption(
        default=True,
        advanced=True,
        help="Verify that all config file values correspond to known options.",
    )
    stats_record_option_scopes = StrListOption(
        advanced=True,
        default=["*"],
        help=softwrap(
            """
            Option scopes to record in stats on run completion.
            Options may be selected by joining the scope and the option with a ^ character,
            i.e. to get option `pantsd` in the GLOBAL scope, you'd pass `GLOBAL^pantsd`.
            Add a '*' to the list to capture all known scopes.
            """
        ),
    )
    pants_ignore = StrListOption(
        advanced=True,
        default=[".*/", _default_rel_distdir, "__pycache__", "!.semgrep/"],
        help=softwrap(
            """
            Paths to ignore for all filesystem operations performed by pants
            (e.g. BUILD file scanning, glob matching, etc).

            Patterns use the gitignore syntax (https://git-scm.com/docs/gitignore).
            The `pants_distdir` and `pants_workdir` locations are automatically ignored.

            `pants_ignore` can be used in tandem with `pants_ignore_use_gitignore`; any rules
            specified here are applied after rules specified in a .gitignore file.
            """
        ),
    )
    pants_ignore_use_gitignore = BoolOption(
        advanced=True,
        default=True,
        help=softwrap(
            """
            Include patterns from `.gitignore`, `.git/info/exclude`, and the global gitignore
            files in the option `[GLOBAL].pants_ignore`, which is used for Pants to ignore
            filesystem operations on those patterns.

            Patterns from `[GLOBAL].pants_ignore` take precedence over these files' rules. For
            example, you can use `!my_pattern` in `pants_ignore` to have Pants operate on files
            that are gitignored.

            Warning: this does not yet support reading nested gitignore files.
            """
        ),
    )
    # These logging options are registered in the bootstrap phase so that plugins can log during
    # registration and not so that their values can be interpolated in configs.
    logdir = StrOption(
        advanced=True,
        default=None,
        metavar="<dir>",
        daemon=True,
        help="Write logs to files under this directory.",
    )
    pantsd = BoolOption(
        default=True,
        daemon=True,
        help=softwrap(
            """
            Enables use of the Pants daemon (pantsd). pantsd can significantly improve
            runtime performance by lowering per-run startup cost, and by memoizing filesystem
            operations and rule execution.
            """
        ),
    )
    # Whether or not to make necessary arrangements to have concurrent runs in pants.
    # In practice, this means that if this is set, a run will not even try to use pantsd.
    # NB: Eventually, we would like to deprecate this flag in favor of making pantsd runs parallelizable.
    concurrent = BoolOption(
        default=False,
        help=softwrap(
            """
            Enable concurrent runs of Pants. With this enabled, Pants will
            start up all concurrent invocations (e.g. in other terminals) without pantsd.
            As a result, enabling this option will increase the per-run startup cost, but
            will not block subsequent invocations.
            """
        ),
    )

    # NB: We really don't want this option to invalidate the daemon, because different clients might have
    # different needs. For instance, an IDE might have a very long timeout because it only wants to refresh
    # a project in the background, while a user might want a shorter timeout for interactivity.
    pantsd_timeout_when_multiple_invocations = FloatOption(
        advanced=True,
        default=60.0,
        help=softwrap(
            """
            The maximum amount of time to wait for the invocation to start until
            raising a timeout exception.
            Because pantsd currently does not support parallel runs,
            any prior running Pants command must be finished for the current one to start.
            To never timeout, use the value -1.
            """
        ),
    )
    pantsd_max_memory_usage = MemorySizeOption(
        advanced=True,
        default=memory_size("4GiB"),
        default_help_repr="4GiB",
        help=softwrap(
            """
            The maximum memory usage of the pantsd process.

            When the maximum memory is exceeded, the daemon will restart gracefully,
            although all previous in-memory caching will be lost. Setting too low means that
            you may miss out on some caching, whereas setting too high may over-consume
            resources and may result in the operating system killing Pantsd due to memory
            overconsumption (e.g. via the OOM killer).

            You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g.
            `2GiB` or `2.12GiB`. A bare number will be in bytes.

            There is at most one pantsd process per workspace.
            """
        ),
    )

    # These facilitate configuring the native engine.
    print_stacktrace = BoolOption(
        advanced=True,
        default=False,
        help="Print the full exception stack trace for any errors.",
    )
    engine_visualize_to = DirOption(
        advanced=True,
        default=None,
        help=softwrap(
            """
            A directory to write execution and rule graphs to as `dot` files. The contents
            of the directory will be overwritten if any filenames collide.
            """
        ),
    )
    # Pants Daemon options.
    pantsd_nailgun_port = IntOption(
        # TODO: The name "pailgun" is likely historical, and this should be renamed to "nailgun".
        "--pantsd-pailgun-port",
        advanced=True,
        default=0,
        daemon=True,
        help="The port to bind the Pants nailgun server to. Defaults to a random port.",
    )
    pantsd_invalidation_globs = StrListOption(
        advanced=True,
        daemon=True,
        help=softwrap(
            """
            Filesystem events matching any of these globs will trigger a daemon restart.
            Pants's own code, plugins, and `--pants-config-files` are inherently invalidated.
            """
        ),
    )
    rule_threads_core = IntOption(
        default=max(2, CPU_COUNT // 2),
        default_help_repr="max(2, #cores/2)",
        advanced=True,
        help=softwrap(
            """
            The number of threads to keep active and ready to execute `@rule` logic (see
            also: `--rule-threads-max`).

            Values less than 2 are not currently supported.

            This value is independent of the number of processes that may be spawned in
            parallel locally (controlled by `--process-execution-local-parallelism`).
            """
        ),
    )
    rule_threads_max = IntOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            The maximum number of threads to use to execute `@rule` logic. Defaults to
            a small multiple of `--rule-threads-core`.
            """
        ),
    )
    cache_instructions = softwrap(
        """
        The path may be absolute or relative. If the directory is within the build root, be
        sure to include it in `--pants-ignore`.
        """
    )
    local_store_dir = StrOption(
        advanced=True,
        help=softwrap(
            f"""
            Directory to use for the local file store, which stores the results of
            subprocesses run by Pants.

            {cache_instructions}
            """
        ),
        # This default is also hard-coded into the engine's rust code in
        # fs::Store::default_path so that tools using a Store outside of pants
        # are likely to be able to use the same storage location.
        default=DEFAULT_LOCAL_STORE_OPTIONS.store_dir,
    )
    local_store_shard_count = IntOption(
        advanced=True,
        help=softwrap(
            """
            The number of LMDB shards created for the local store. This setting also impacts
            the maximum size of stored files: see `--local-store-files-max-size-bytes`
            for more information.

            Because LMDB allows only one simultaneous writer per database, the store is split
            into multiple shards to allow for more concurrent writers. The faster your disks
            are, the fewer shards you are likely to need for performance.

            NB: After changing this value, you will likely want to manually clear the
            `--local-store-dir` directory to clear the space used by old shard layouts.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.shard_count,
    )
    local_store_processes_max_size_bytes = IntOption(
        advanced=True,
        help=softwrap(
            """
            The maximum size in bytes of the local store containing process cache entries.
            Stored below `--local-store-dir`.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.processes_max_size_bytes,
    )
    local_store_files_max_size_bytes = IntOption(
        advanced=True,
        help=softwrap(
            """
            The maximum size in bytes of the local store containing files.
            Stored below `--local-store-dir`.

            NB: This size value bounds the total size of all files, but (due to sharding of the
            store on disk) it also bounds the per-file size to (VALUE /
            `--local-store-shard-count`).

            This value doesn't reflect space allocated on disk, or RAM allocated (it
            may be reflected in VIRT but not RSS). However, the default is lower than you
            might otherwise choose because macOS creates core dumps that include MMAP'd
            pages, and setting this too high might cause core dumps to use an unreasonable
            amount of disk if they are enabled.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.files_max_size_bytes,
    )
    local_store_directories_max_size_bytes = IntOption(
        advanced=True,
        help=softwrap(
            """
            The maximum size in bytes of the local store containing directories.
            Stored below `--local-store-dir`.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.directories_max_size_bytes,
    )
    _named_caches_dir = StrOption(
        advanced=True,
        help=softwrap(
            f"""
            Directory to use for named global caches for tools and processes with trusted,
            concurrency-safe caches.

            {cache_instructions}
            """
        ),
        default=os.path.join(get_pants_cachedir(), "named_caches"),
    )
    local_execution_root_dir = StrOption(
        advanced=True,
        help=softwrap(
            f"""
            Directory to use for local process execution sandboxing.

            {cache_instructions}
            """
        ),
        default=tempfile.gettempdir(),
        default_help_repr="<tmp_dir>",
    )
    local_cache = BoolOption(
        default=DEFAULT_EXECUTION_OPTIONS.local_cache,
        help=softwrap(
            """
            Whether to cache process executions in a local cache persisted to disk at
            `--local-store-dir`.
            """
        ),
    )
    process_cleanup = BoolOption(
        default=(DEFAULT_EXECUTION_OPTIONS.keep_sandboxes == KeepSandboxes.never),
        removal_version="3.0.0.dev0",
        removal_hint="Use the `keep_sandboxes` option instead.",
        help=softwrap(
            """
            If false, Pants will not clean up local directories used as chroots for running
            processes. Pants will log their location so that you can inspect the chroot, and
            run the `__run.sh` script to recreate the process using the same argv and
            environment variables used by Pants. This option is useful for debugging.
            """
        ),
    )
    keep_sandboxes = EnumOption(
        default=DEFAULT_EXECUTION_OPTIONS.keep_sandboxes,
        help=softwrap(
            """
            Controls whether Pants will clean up local directories used as chroots for running
            processes.

            Pants will log their location so that you can inspect the chroot, and run the
            `__run.sh` script to recreate the process using the same argv and environment variables
            used by Pants. This option is useful for debugging.
            """
        ),
    )
    cache_content_behavior = EnumOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.cache_content_behavior,
        help=softwrap(
            """
            Controls how the content of cache entries is handled during process execution.

            When using a remote cache, the `fetch` behavior will fetch remote cache content from the
            remote store before considering the cache lookup a hit, while the `validate` behavior
            will only validate (for either a local or remote cache) that the content exists, without
            fetching it.

            The `defer` behavior, on the other hand, will neither fetch nor validate the cache
            content before calling a cache hit a hit. This "defers" actually fetching the cache
            entry until Pants needs it (which may be never).

            The `defer` mode is the most network efficient (because it will completely skip network
            requests in many cases), followed by the `validate` mode (since it can still skip
            fetching the content if no consumer ends up needing it). But both the `validate` and
            `defer` modes rely on an experimental feature called "backtracking" to attempt to
            recover if content later turns out to be missing (`validate` has a much narrower window
            for backtracking though, since content would need to disappear between validation and
            consumption: generally, within one `pantsd` session).
            """
        ),
    )
    ca_certs_path = StrOption(
        advanced=True,
        default=None,
        help=softwrap(
            f"""
            Path to a file containing PEM-format CA certificates used for verifying secure
            connections when downloading files required by a build.

            Even when using the `docker_environment` and `remote_environment` targets, this path
            will be read from the local host, and those certs will be used in the environment.

            This option cannot be overridden via environment targets, so if you need a different
            value than what the rest of your organization is using, override the value via an
            environment variable, CLI argument, or `.pants.rc` file. See {doc_url('options')}.
            """
        ),
    )
    process_total_child_memory_usage = MemorySizeOption(
        advanced=True,
        default=None,
        help=softwrap(
            """
            The maximum memory usage for all "pooled" child processes.

            When set, this value participates in precomputing the pool size of child processes
            used by Pants (pooling is currently used only for the JVM). When not set, Pants will
            default to spawning `2 * --process-execution-local-parallelism` pooled processes.

            A high value would result in a high number of child processes spawned, potentially
            overconsuming your resources and triggering the OS' OOM killer. A low value would
            mean a low number of child processes launched and therefore less parallelism for the
            tasks that need those processes.

            If setting this value, consider also adjusting the value of the
            `--process-per-child-memory-usage` option.

            You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g.
            `2GiB` or `2.12GiB`. A bare number will be in bytes.
            """
        ),
    )
    process_per_child_memory_usage = MemorySizeOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.process_per_child_memory_usage,
        default_help_repr=_PER_CHILD_MEMORY_USAGE,
        help=softwrap(
            """
            The default memory usage for a single "pooled" child process.

            Check the documentation for the `--process-total-child-memory-usage` for advice on
            how to choose an appropriate value for this option.

            You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g.
            `2GiB` or `2.12GiB`. A bare number will be in bytes.
            """
        ),
    )
    process_execution_local_parallelism = IntOption(
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_parallelism,
        default_help_repr="#cores",
        advanced=True,
        help=softwrap(
            """
            Number of concurrent processes that may be executed locally.

            This value is independent of the number of threads that may be used to
            execute the logic in `@rules` (controlled by `--rule-threads-core`).
            """
        ),
    )
    process_execution_remote_parallelism = IntOption(
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_remote_parallelism,
        advanced=True,
        help="Number of concurrent processes that may be executed remotely.",
    )
    process_execution_cache_namespace = StrOption(
        advanced=True,
        default=cast(str, DEFAULT_EXECUTION_OPTIONS.process_execution_cache_namespace),
        help=softwrap(
            """
            The cache namespace for process execution.
            Change this value to invalidate every artifact's execution, or to prevent
            process cache entries from being (re)used for different usecases or users.
            """
        ),
    )
    process_execution_local_enable_nailgun = BoolOption(
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_enable_nailgun,
        help="Whether or not to use nailgun to run JVM requests that are marked as supporting nailgun.",
        advanced=True,
    )
    process_execution_graceful_shutdown_timeout = IntOption(
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_graceful_shutdown_timeout,
        help=softwrap(
            f"""
            The time in seconds to wait when gracefully shutting down an interactive process (such
            as one opened using `{bin_name()} run`) before killing it.
            """
        ),
        advanced=True,
    )
    session_end_tasks_timeout = FloatOption(
        default=3.0,
        help=softwrap(
            """
            The time in seconds to wait for still-running "session end" tasks to complete before finishing
            completion of a Pants invocation. "Session end" tasks include, for example, writing data that was
            generated during the applicable Pants invocation to a configured remote cache.
            """
        ),
    )
    remote_execution = BoolOption(
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution,
        help=softwrap(
            """
            Enables remote workers for increased parallelism. (Alpha)

            Alternatively, you can use `[GLOBAL].remote_cache_read` and `[GLOBAL].remote_cache_write` to still run
            everything locally, but to use a remote cache.
            """
        ),
    )
    remote_cache_read = BoolOption(
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_read,
        help=softwrap(
            """
            Whether to enable reading from a remote cache.

            This cannot be used at the same time as `[GLOBAL].remote_execution`.
            """
        ),
    )
    remote_cache_write = BoolOption(
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_write,
        help=softwrap(
            """
            Whether to enable writing results to a remote cache.

            This cannot be used at the same time as `[GLOBAL].remote_execution`.
            """
        ),
    )
    # TODO: update all these remote_... option helps for the new support for non-REAPI schemes
    remote_instance_name = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Name of the remote instance to use by remote caching and remote execution.

            This is used by some remote servers for routing. Consult your remote server for
            whether this should be set.

            You can also use a Pants plugin which provides remote authentication to dynamically
            set this value.
            """
        ),
    )
    remote_ca_certs_path = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a PEM file containing CA certificates used for verifying secure
            connections to `[GLOBAL].remote_execution_address` and `[GLOBAL].remote_store_address`.

            If unspecified, Pants will attempt to auto-discover root CA certificates when TLS
            is enabled with remote execution and caching.
            """
        ),
    )
    remote_client_certs_path = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a PEM file containing client certificates used for verifying secure connections to
            `[GLOBAL].remote_execution_address` and `[GLOBAL].remote_store_address` when using
            client authentication (mTLS).

            If unspecified, will use regular TLS. Requires `remote_client_key_path` to also be
            specified.
            """
        ),
    )

    remote_client_key_path = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a PEM file containing a private key used for verifying secure connections to
            `[GLOBAL].remote_execution_address` and `[GLOBAL].remote_store_address` when using
            client authentication (mTLS).

            If unspecified, will use regular TLS. Requires `remote_client_certs_path` to also be
            specified.
            """
        ),
    )
    remote_oauth_bearer_token_path = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a file containing an oauth token to use for gGRPC connections to
            `[GLOBAL].remote_execution_address` and `[GLOBAL].remote_store_address`.

            If specified, Pants will add a header in the format `authorization: Bearer <token>`.
            You can also manually add this header via `[GLOBAL].remote_execution_headers` and
            `[GLOBAL].remote_store_headers`, or use `[GLOBAL].remote_auth_plugin` to provide a plugin to
            dynamically set the relevant headers. Otherwise, no authorization will be performed.
            """
        ),
        removal_version="2.21.0.dev0",
        removal_hint=f'use `[GLOBAL].remote_oauth_bearer_token = "@/path/to/token.txt"` instead, see {doc_url("reference-global#remote_oauth_bearer_token")}',
    )

    remote_oauth_bearer_token = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            f"""
            An oauth token to use for gGRPC connections to
            `[GLOBAL].remote_execution_address` and `[GLOBAL].remote_store_address`.

            If specified, Pants will add a header in the format `authorization: Bearer <token>`.
            You can also manually add this header via `[GLOBAL].remote_execution_headers` and
            `[GLOBAL].remote_store_headers`, or use `[GLOBAL].remote_auth_plugin` to provide a plugin to
            dynamically set the relevant headers. Otherwise, no authorization will be performed.

            Recommendation: do not place a token directly in `pants.toml`, instead do one of: set
            the token via the environment variable (`PANTS_REMOTE_OAUTH_BEARER_TOKEN`), CLI option
            (`--remote-oauth-bearer-token`), or store the token in a file and set the option to
            `"@/path/to/token.txt"` to [read the value from that
            file]({doc_url('options#reading-individual-option-values-from-files')}).
            """
        ),
    )
    remote_store_address = StrOption(
        advanced=True,
        default=cast(str, DEFAULT_EXECUTION_OPTIONS.remote_store_address),
        help=_RemoteAddressScheme.address_help(
            "remote file store",
            extra="",
            requires_execution=False,
        ),
    )
    remote_store_headers = DictOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_headers,
        help=softwrap(
            """
            Headers to set on remote store requests.

            Format: header=value. Pants may add additional headers.

            See `[GLOBAL].remote_execution_headers` as well.
            """
        ),
        default_help_repr=repr(DEFAULT_EXECUTION_OPTIONS.remote_store_headers).replace(
            VERSION, "<pants_version>"
        ),
    )
    remote_store_chunk_bytes = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_bytes,
        help="Size in bytes of chunks transferred to/from the remote file store.",
    )
    remote_store_rpc_retries = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_retries,
        help="Number of times to retry any RPC to the remote store before giving up.",
    )
    remote_store_rpc_concurrency = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_concurrency,
        help="The number of concurrent requests allowed to the remote store service.",
    )
    remote_store_rpc_timeout_millis = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_timeout_millis,
        help="Timeout value for remote store RPCs (not including streaming requests) in milliseconds.",
    )
    remote_store_batch_api_size_limit = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_batch_api_size_limit,
        help="The maximum total size of blobs allowed to be sent in a single batch API call to the remote store.",
    )
    remote_cache_warnings = EnumOption(
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_warnings,
        advanced=True,
        help=softwrap(
            """
            How frequently to log remote cache failures at the `warn` log level.

            All errors not logged at the `warn` level will instead be logged at the
            `debug` level.
            """
        ),
    )
    remote_cache_rpc_concurrency = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_rpc_concurrency,
        help="The number of concurrent requests allowed to the remote cache service.",
    )
    remote_cache_rpc_timeout_millis = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_rpc_timeout_millis,
        help="Timeout value for remote cache RPCs in milliseconds.",
    )
    remote_execution_address = StrOption(
        advanced=True,
        default=cast(str, DEFAULT_EXECUTION_OPTIONS.remote_execution_address),
        help=_RemoteAddressScheme.address_help(
            "remote execution scheduler",
            extra="You must also set `[GLOBAL].remote_store_address`, which will often be the same value.",
            requires_execution=True,
        ),
    )
    remote_execution_headers = DictOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_headers,
        help=softwrap(
            """
            Headers to set on remote execution requests. Format: header=value. Pants
            may add additional headers.

            See `[GLOBAL].remote_store_headers` as well.
            """
        ),
        default_help_repr=repr(DEFAULT_EXECUTION_OPTIONS.remote_execution_headers).replace(
            VERSION, "<pants_version>"
        ),
    )
    remote_execution_overall_deadline_secs = IntOption(
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_overall_deadline_secs,
        advanced=True,
        help="Overall timeout in seconds for each remote execution request from time of submission",
    )
    remote_execution_rpc_concurrency = IntOption(
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_rpc_concurrency,
        help="The number of concurrent requests allowed to the remote execution service.",
    )
    remote_execution_append_only_caches_base_path = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Sets the base path to use when setting up an append-only cache for a process running remotely.
            If this option is not set, then append-only caches will not be used with remote execution.
            The option should be set to the absolute path of a writable directory in the remote execution
            environment where Pants can create append-only caches for use with remotely executing processes.
            """
        ),
    )
    watch_filesystem = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            Set to False if Pants should not watch the filesystem for changes. `pantsd` or `loop`
            may not be enabled.
            """
        ),
    )


# N.B. By subclassing BootstrapOptions, we inherit all of those options and are also able to extend
# it with non-bootstrap options too.
class GlobalOptions(BootstrapOptions, Subsystem):
    options_scope = GLOBAL_SCOPE
    help = "Options to control the overall behavior of Pants."

    colors = BoolOption(
        default=sys.stdout.isatty(),
        help=softwrap(
            """
            Whether Pants should use colors in output or not. This may also impact whether
            some tools Pants runs use color.

            When unset, this value defaults based on whether the output destination supports color.
            """
        ),
    )
    dynamic_ui = BoolOption(
        default=(("CI" not in os.environ) and sys.stderr.isatty()),
        help=softwrap(
            """
            Display a dynamically-updating console UI as Pants runs. This is true by default
            if Pants detects a TTY and there is no 'CI' environment variable indicating that
            Pants is running in a continuous integration environment.
            """
        ),
    )
    dynamic_ui_renderer = EnumOption(
        default=DynamicUIRenderer.indicatif_spinner,
        help="If `--dynamic-ui` is enabled, selects the renderer.",
    )
    dynamic_ui_log_streaming = BoolOption(
        default=False,
        help=softwrap(
            """
            If `--dynamic-ui` is enabled, whether to stream logs to the UI.

            Does not support prodash renderer.
            """
        ),
    )
    dynamic_ui_log_streaming_lines = IntOrStrOption(
        allowed_string_values=["auto"],
        default=1,
        help=softwrap(
            """
            If `--dynamic-ui` and `--dynamic-ui-log-streaming` is enabled, the number
            of lines to stream to the UI.

            This can be either a positive integer or the string `auto`, which will attempt
            to show a reasonable number of log lines based on the terminal height and the
            number of `topn` processes to show logs for.
            """
        ),
    )
    dynamic_ui_log_streaming_topn = IntOrStrOption(
        allowed_string_values=["auto"],
        default=10,
        help=softwrap(
            """
            If `--dynamic-ui` and `--dynamic-ui-log-streaming` is enabled, the number
            of heavy processes to stream to the UI.

            This can be either a positive integer or the string `auto`, which will attempt
            to show a reasonable number of processes based on the terminal height and the
            number of log lines to show. If log lines are also set to `auto` half of the
            processes will be shown.
            """
        ),
    )

    tag = StrListOption(
        help=softwrap(
            f"""
            Include only targets with these tags (optional '+' prefix) or without these
            tags ('-' prefix). See {doc_url('advanced-target-selection')}.
            """
        ),
        metavar="[+-]tag1,tag2,...",
    )

    unmatched_build_file_globs = EnumOption(
        default=GlobMatchErrorBehavior.warn,
        help=softwrap(
            """
            What to do when files and globs specified in BUILD files, such as in the
            `sources` field, cannot be found.

            This usually happens when the files do not exist on your machine. It can also happen
            if they are ignored by the `[GLOBAL].pants_ignore` option, which causes the files to be
            invisible to Pants.
            """
        ),
        advanced=True,
    )
    unmatched_cli_globs = EnumOption(
        default=GlobMatchErrorBehavior.error,
        help=softwrap(
            """
            What to do when command line arguments, e.g. files and globs like `dir::`, cannot be
            found.

            This usually happens when the files do not exist on your machine. It can also happen
            if they are ignored by the `[GLOBAL].pants_ignore` option, which causes the files to be
            invisible to Pants.
            """
        ),
        advanced=True,
    )

    build_patterns = StrListOption(
        default=["BUILD", "BUILD.*"],
        help=softwrap(
            """
            The naming scheme for BUILD files, i.e. where you define targets.

            This only sets the naming scheme, not the directory paths to look for. To add
            ignore patterns, use the option `[GLOBAL].build_ignore`.

            You may also need to update the option `[tailor].build_file_name` so that it is
            compatible with this option.
            """
        ),
        advanced=True,
    )

    build_ignore = StrListOption(
        help=softwrap(
            """
            Path globs or literals to ignore when identifying BUILD files.

            This does not affect any other filesystem operations; use `--pants-ignore` for
            that instead.
            """
        ),
        advanced=True,
    )
    build_file_prelude_globs = StrListOption(
        help=softwrap(
            f"""
            Python files to evaluate and whose symbols should be exposed to all BUILD files.
            See {doc_url('macros')}.
            """
        ),
        advanced=True,
    )
    subproject_roots = StrListOption(
        help="Paths that correspond with build roots for any subproject that this project depends on.",
        advanced=True,
    )

    loop = BoolOption(default=False, help="Run goals continuously as file changes are detected.")
    loop_max = IntOption(
        default=2**32,
        help="The maximum number of times to loop when `--loop` is specified.",
        advanced=True,
    )

    streaming_workunits_report_interval = FloatOption(
        default=1.0,
        help="Interval in seconds between when streaming workunit event receivers will be polled.",
        advanced=True,
    )
    streaming_workunits_level = EnumOption(
        default=LogLevel.DEBUG,
        help=softwrap(
            """
            The level of workunits that will be reported to streaming workunit event receivers.

            Workunits form a tree, and even when workunits are filtered out by this setting, the
            workunit tree structure will be preserved (by adjusting the parent pointers of the
            remaining workunits).
            """
        ),
        advanced=True,
    )
    streaming_workunits_complete_async = BoolOption(
        default=not is_in_container(),
        help=softwrap(
            """
            True if stats recording should be allowed to complete asynchronously when `pantsd`
            is enabled. When `pantsd` is disabled, stats recording is always synchronous.
            To reduce data loss, this flag defaults to false inside of containers, such as
            when run with Docker.
            """
        ),
        advanced=True,
    )

    docker_execution = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            If true, `docker_environment` targets can be used to run builds inside a Docker
            container.

            If false, anytime a `docker_environment` target is used, Pants will instead fallback to
            whatever the target's `fallback_environment` field is set to.

            This can be useful, for example, if you want to always use Docker locally, but disable
            it in CI, or vice versa.
            """
        ),
    )
    remote_execution_extra_platform_properties = StrListOption(
        advanced=True,
        help=softwrap(
            """
            Platform properties to set on remote execution requests.

            Format: `property=value`. Multiple values should be specified as multiple
            occurrences of this flag.

            Pants itself may add additional platform properties.

            If you are using the `remote_environment` target mechanism, set this value as a field
            on the target instead. This option will be ignored.
            """
        ),
        default=[],
    )

    @classmethod
    def validate_instance(cls, opts):
        """Validates an instance of global options for cases that are not prohibited via
        registration.

        For example: mutually exclusive options may be registered by passing a `mutually_exclusive_group`,
        but when multiple flags must be specified together, it can be necessary to specify post-parse
        checks.

        Raises pants.option.errors.OptionsError on validation failure.
        """
        if opts.rule_threads_core < 2:
            # TODO: This is a defense against deadlocks due to #11329: we only run one `@goal_rule`
            # at a time, and a `@goal_rule` will only block one thread.
            raise OptionsError(
                softwrap(
                    f"""
                    --rule-threads-core values less than 2 are not supported, but it was set to
                    {opts.rule_threads_core}.
                    """
                )
            )

        if (
            opts.process_total_child_memory_usage is not None
            and opts.process_total_child_memory_usage < opts.process_per_child_memory_usage
        ):
            raise OptionsError(
                softwrap(
                    f"""
                    Nailgun pool can not be initialised as the total amount of memory allowed is \
                    smaller than the memory allocation for a single child process.

                    - total child process memory allowed: {fmt_memory_size(opts.process_total_child_memory_usage)}

                    - default child process memory: {fmt_memory_size(opts.process_per_child_memory_usage)}
                    """
                )
            )

        if not opts.watch_filesystem and (opts.pantsd or opts.loop):
            raise OptionsError(
                softwrap(
                    """
                    The `--no-watch-filesystem` option may not be set if
                    `--pantsd` or `--loop` is set.
                    """
                )
            )

        if opts.remote_execution_address:
            _RemoteAddressScheme.validate_address(
                opts.remote_execution_address,
                require_execution=True,
                context_for_diagnostics="The `[GLOBAL].remote_execution_address` option",
            )
        if opts.remote_store_address:
            _RemoteAddressScheme.validate_address(
                opts.remote_store_address,
                require_execution=False,
                context_for_diagnostics="The `[GLOBAL].remote_store_address` option",
            )

        # Ensure that remote headers are ASCII.
        def validate_remote_headers(opt_name: str) -> None:
            command_line_opt_name = f"--{opt_name.replace('_', '-')}"
            for k, v in getattr(opts, opt_name).items():
                if not k.isascii():
                    raise OptionsError(
                        softwrap(
                            f"""
                            All values in `{command_line_opt_name}` must be ASCII, but the key
                            in `{k}: {v}` has non-ASCII characters.
                            """
                        )
                    )
                if not v.isascii():
                    raise OptionsError(
                        softwrap(
                            f"""
                            All values in `{command_line_opt_name}` must be ASCII, but the value in
                            `{k}: {v}` has non-ASCII characters.
                            """
                        )
                    )

        validate_remote_headers("remote_execution_headers")
        validate_remote_headers("remote_store_headers")

        is_remote_client_key_set = opts.remote_client_key_path is not None
        is_remote_client_certs_set = opts.remote_client_certs_path is not None
        if is_remote_client_key_set != is_remote_client_certs_set:
            raise OptionsError(
                softwrap(
                    """
                    `--remote-client-key-path` and `--remote-client-certs-path` must be specified
                    together.
                    """
                )
            )

        illegal_build_ignores = [i for i in opts.build_ignore if i.startswith("!")]
        if illegal_build_ignores:
            raise OptionsError(
                softwrap(
                    f"""
                    The `--build-ignore` option does not support negated globs, but was
                    given: {illegal_build_ignores}.
                    """
                )
            )

    @staticmethod
    def create_py_executor(bootstrap_options: OptionValueContainer) -> PyExecutor:
        rule_threads_max = (
            bootstrap_options.rule_threads_max
            if bootstrap_options.rule_threads_max
            else 4 * bootstrap_options.rule_threads_core
        )
        return PyExecutor(
            core_threads=bootstrap_options.rule_threads_core, max_threads=rule_threads_max
        )

    @staticmethod
    def resolve_keep_sandboxes(
        bootstrap_options: OptionValueContainer,
    ) -> KeepSandboxes:
        resolved_value = resolve_conflicting_options(
            old_option="process_cleanup",
            new_option="keep_sandboxes",
            old_scope="",
            new_scope="",
            old_container=bootstrap_options,
            new_container=bootstrap_options,
        )

        if isinstance(resolved_value, bool):
            # Is `process_cleanup`.
            return KeepSandboxes.never if resolved_value else KeepSandboxes.always
        elif isinstance(resolved_value, KeepSandboxes):
            return resolved_value
        else:
            raise TypeError(f"Unexpected option value for `keep_sandboxes`: {resolved_value}")

    @staticmethod
    def compute_pants_ignore(buildroot, global_options):
        """Computes the merged value of the `--pants-ignore` flag.

        This inherently includes the workdir and distdir locations if they are located under the
        buildroot.
        """
        pants_ignore = list(global_options.pants_ignore)

        def add(absolute_path, include=False):
            # To ensure that the path is ignored regardless of whether it is a symlink or a directory, we
            # strip trailing slashes (which would signal that we wanted to ignore only directories).
            maybe_rel_path = fast_relpath_optional(absolute_path, buildroot)
            if maybe_rel_path:
                rel_path = maybe_rel_path.rstrip(os.path.sep)
                prefix = "!" if include else ""
                pants_ignore.append(f"{prefix}/{rel_path}")

        add(global_options.pants_workdir)
        add(global_options.pants_distdir)
        add(global_options.pants_subprocessdir)

        return pants_ignore

    @staticmethod
    def compute_pantsd_invalidation_globs(
        buildroot: str, bootstrap_options: OptionValueContainer
    ) -> tuple[str, ...]:
        """Computes the merged value of the `--pantsd-invalidation-globs` option.

        Combines --pythonpath and --pants-config-files files that are in {buildroot} dir with those
        invalidation_globs provided by users.
        """
        invalidation_globs: OrderedSet[str] = OrderedSet()

        # Globs calculated from the sys.path and other file-like configuration need to be sanitized
        # to relative globs (where possible).
        potentially_absolute_globs = (
            *sys.path,
            *bootstrap_options.pythonpath,
            *bootstrap_options.pants_config_files,
        )
        for glob in potentially_absolute_globs:
            # NB: We use `relpath` here because these paths are untrusted, and might need to be
            # normalized in addition to being relativized.
            glob_relpath = (
                os.path.relpath(glob, buildroot) if os.path.isabs(glob) else os.path.normpath(glob)
            )
            if glob_relpath == "." or glob_relpath.startswith(".."):
                logger.debug(
                    f"Changes to {glob}, outside of the buildroot, will not be invalidated."
                )
                continue

            invalidation_globs.update([glob_relpath, glob_relpath + "/**"])

        # Explicitly specified globs are already relative, and are added verbatim.
        invalidation_globs.update(
            ("!*.pyc", "!__pycache__/", ".gitignore", *bootstrap_options.pantsd_invalidation_globs)
        )
        return tuple(invalidation_globs)

    @memoized_classmethod
    def get_options_flags(cls) -> GlobalOptionsFlags:
        return GlobalOptionsFlags.create(cast("Type[GlobalOptions]", cls))

    @memoized_property
    def named_caches_dir(self) -> PurePath:
        return Path(self._named_caches_dir).resolve()

    def output_simplifier(self) -> Simplifier:
        """Create a `Simplifier` instance for use on stdout and stderr that will be shown to a
        user."""
        return Simplifier(
            # it's ~never useful to show the chroot path to a user
            strip_chroot_path=True,
            strip_formatting=not self.colors,
        )


@dataclass(frozen=True)
class GlobalOptionsFlags:
    flags: FrozenOrderedSet[str]
    short_flags: FrozenOrderedSet[str]

    @classmethod
    def create(cls, GlobalOptionsType: type[GlobalOptions]) -> GlobalOptionsFlags:
        flags = set()
        short_flags = set()

        for options_info in collect_options_info(BootstrapOptions):
            for flag in options_info.flag_names:
                flags.add(flag)
                if len(flag) == 2:
                    short_flags.add(flag)
                elif options_info.flag_options.get("type") == bool:
                    flags.add(f"--no-{flag[2:]}")

        return cls(FrozenOrderedSet(flags), FrozenOrderedSet(short_flags))


@dataclass(frozen=True)
class ProcessCleanupOption:
    """A wrapper around the global option `process_cleanup`.

    Prefer to use this rather than requesting `GlobalOptions` for more precise invalidation.
    """

    val: bool


@dataclass(frozen=True)
class NamedCachesDirOption:
    """A wrapper around the global option `named_caches_dir`.

    Prefer to use this rather than requesting `GlobalOptions` for more precise invalidation.
    """

    val: PurePath


def ca_certs_path_to_file_content(path: str) -> FileContent:
    """Set up FileContent for using the ca_certs_path locally in a process sandbox.

    This helper can be used when setting up a Process so that the certs are included in the process.
    Use `Get(Digest, CreateDigest)`, and then include this in the `input_digest` for the Process.
    Typically, you will also need to configure the invoking tool to load those certs, via its argv
    or environment variables.

    Note that the certs are always read on the localhost, even when using Docker and remote
    execution. Then, those certs can be copied into the process.

    Warning: this will not detect when the contents of cert files changes, because we use
    `pathlib.Path.read_bytes()`. Better would be
    # https://github.com/pantsbuild/pants/issues/10842
    """
    return FileContent(os.path.basename(path), Path(path).read_bytes())
