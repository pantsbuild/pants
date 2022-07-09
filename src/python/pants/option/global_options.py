# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import importlib
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Type, cast

from pants.base.build_environment import (
    get_buildroot,
    get_default_pants_config_file,
    get_pants_cachedir,
    is_in_container,
    pants_version,
)
from pants.base.deprecated import warn_or_error
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.environment import CompleteEnvironment
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
from pants.util.strutil import fmt_memory_size, softwrap
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


class UnmatchedBuildFileGlobs(Enum):
    """What to do when globs do not match in BUILD files."""

    warn = "warn"
    error = "error"

    def to_glob_match_error_behavior(self) -> GlobMatchErrorBehavior:
        return GlobMatchErrorBehavior(self.value)


class UnmatchedCliGlobs(Enum):
    """What to do when globs do not match in CLI args."""

    ignore = "ignore"
    warn = "warn"
    error = "error"

    def to_glob_match_error_behavior(self) -> GlobMatchErrorBehavior:
        return GlobMatchErrorBehavior(self.value)


class OwnersNotFoundBehavior(Enum):
    """What to do when a file argument cannot be mapped to an owning target."""

    ignore = "ignore"
    warn = "warn"
    error = "error"

    def to_glob_match_error_behavior(self) -> GlobMatchErrorBehavior:
        return GlobMatchErrorBehavior(self.value)


@enum.unique
class RemoteCacheWarningsBehavior(Enum):
    ignore = "ignore"
    first_only = "first_only"
    backoff = "backoff"


@enum.unique
class AuthPluginState(Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AuthPluginResult:
    """The return type for a function specified via `--remote-auth-plugin`.

    The returned `store_headers` and `execution_headers` will replace whatever headers Pants would
    have used normally, e.g. what is set with `--remote-store-headers`. This allows you to control
    the merge strategy if your plugin sets conflicting headers. Usually, you will want to preserve
    the `initial_store_headers` and `initial_execution_headers` passed to the plugin.

    If set, the returned `instance_name` will override by `--remote-instance-name`, `store_address`
    will override `--remote-store-address`, and `execution_address` will override
    `--remote-execution-address`. The store address and execution address must be prefixed with
    `grpc://` or `grpcs://`.
    """

    state: AuthPluginState
    store_headers: dict[str, str]
    execution_headers: dict[str, str]
    store_address: str | None = None
    execution_address: str | None = None
    instance_name: str | None = None
    expiration: datetime | None = None

    def __post_init__(self) -> None:
        def assert_valid_address(addr: str | None, field_name: str) -> None:
            valid_schemes = [f"{scheme}://" for scheme in ("grpc", "grpcs")]
            if addr and not any(addr.startswith(scheme) for scheme in valid_schemes):
                raise ValueError(
                    f"Invalid `{field_name}` in `AuthPluginResult` returned from "
                    f"`--remote-auth-plugin`. Must start with `grpc://` or `grpcs://`, but was "
                    f"{addr}."
                )

        assert_valid_address(self.store_address, "store_address")
        assert_valid_address(self.execution_address, "execution_address")

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

    @classmethod
    def disabled(cls) -> DynamicRemoteOptions:
        return DynamicRemoteOptions(
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
    def from_options(
        cls,
        full_options: Options,
        env: CompleteEnvironment,
        prior_result: AuthPluginResult | None = None,
    ) -> tuple[DynamicRemoteOptions, AuthPluginResult | None]:
        bootstrap_options = full_options.bootstrap_option_values()
        assert bootstrap_options is not None
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

        if bootstrap_options.remote_oauth_bearer_token_path:
            oauth_token = (
                Path(bootstrap_options.remote_oauth_bearer_token_path).resolve().read_text().strip()
            )
            if set(oauth_token).intersection({"\n", "\r"}):
                raise OptionsError(
                    f"OAuth bearer token path {bootstrap_options.remote_oauth_bearer_token_path} "
                    "must not contain multiple lines."
                )
            token_header = {"authorization": f"Bearer {oauth_token}"}
            execution_headers.update(token_header)
            store_headers.update(token_header)

        auth_plugin_result: AuthPluginResult | None = None
        if (
            bootstrap_options.remote_auth_plugin
            and bootstrap_options.remote_auth_plugin.strip()
            and (execution or cache_read or cache_write)
        ):
            if ":" not in bootstrap_options.remote_auth_plugin:
                raise OptionsError(
                    "Invalid value for `--remote-auth-plugin`: "
                    f"{bootstrap_options.remote_auth_plugin}. Please use the format "
                    f"`path.to.module:my_func`."
                )
            auth_plugin_path, auth_plugin_func = bootstrap_options.remote_auth_plugin.split(":")
            auth_plugin_module = importlib.import_module(auth_plugin_path)
            auth_plugin_func = getattr(auth_plugin_module, auth_plugin_func)
            auth_plugin_result = cast(
                AuthPluginResult,
                auth_plugin_func(
                    initial_execution_headers=execution_headers,
                    initial_store_headers=store_headers,
                    options=full_options,
                    env=dict(env),
                    prior_result=prior_result,
                ),
            )
            if not auth_plugin_result.is_available:
                # NB: This is debug because we expect plugins to log more informative messages.
                logger.debug(
                    "Disabling remote caching and remote execution because authentication was not "
                    "available via the plugin from `--remote-auth-plugin`."
                )
                execution = False
                cache_read = False
                cache_write = False
            else:
                logger.debug(
                    "`--remote-auth-plugin` succeeded. Remote caching/execution will be attempted."
                )
                execution_headers = auth_plugin_result.execution_headers
                store_headers = auth_plugin_result.store_headers
                overridden_opt_log = (
                    "Overriding `{}` to instead be {} due to the plugin from "
                    "`--remote-auth-plugin`."
                )
                if (
                    auth_plugin_result.instance_name is not None
                    and auth_plugin_result.instance_name != instance_name
                ):
                    logger.debug(
                        overridden_opt_log.format(
                            f"--remote-instance-name={repr(instance_name)}",
                            repr(auth_plugin_result.instance_name),
                        )
                    )
                    instance_name = auth_plugin_result.instance_name
                if (
                    auth_plugin_result.store_address is not None
                    and auth_plugin_result.store_address != store_address
                ):
                    logger.debug(
                        overridden_opt_log.format(
                            f"--remote-store-address={repr(store_address)}",
                            repr(auth_plugin_result.store_address),
                        )
                    )
                    store_address = auth_plugin_result.store_address
                if (
                    auth_plugin_result.execution_address is not None
                    and auth_plugin_result.execution_address != execution_address
                ):
                    logger.debug(
                        overridden_opt_log.format(
                            f"--remote-execution-address={repr(execution_address)}",
                            repr(auth_plugin_result.execution_address),
                        )
                    )
                    execution_address = auth_plugin_result.execution_address

        # NB: Tonic expects the schemes `http` and `https`, even though they are gRPC requests.
        # We validate that users set `grpc` and `grpcs` in the options system / plugin for clarity,
        # but then normalize to `http`/`https`.
        execution_address = (
            re.sub(r"^grpc", "http", execution_address) if execution_address else None
        )
        store_address = re.sub(r"^grpc", "http", store_address) if store_address else None

        opts = DynamicRemoteOptions(
            execution=execution,
            cache_read=cache_read,
            cache_write=cache_write,
            instance_name=instance_name,
            store_address=store_address,
            execution_address=execution_address,
            store_headers=store_headers,
            execution_headers=execution_headers,
            parallelism=parallelism,
            store_rpc_concurrency=store_rpc_concurrency,
            cache_rpc_concurrency=cache_rpc_concurrency,
            execution_rpc_concurrency=execution_rpc_concurrency,
        )
        return opts, auth_plugin_result


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

    process_cleanup: bool
    local_cache: bool
    process_execution_local_parallelism: int
    process_execution_local_enable_nailgun: bool
    process_execution_remote_parallelism: int
    process_execution_cache_namespace: str | None
    process_execution_graceful_shutdown_timeout: int

    process_total_child_memory_usage: int | None
    process_per_child_memory_usage: int

    remote_store_address: str | None
    remote_store_headers: dict[str, str]
    remote_store_chunk_bytes: Any
    remote_store_chunk_upload_timeout_seconds: int
    remote_store_rpc_retries: int
    remote_store_rpc_concurrency: int
    remote_store_batch_api_size_limit: int

    remote_cache_eager_fetch: bool
    remote_cache_warnings: RemoteCacheWarningsBehavior
    remote_cache_rpc_concurrency: int
    remote_cache_read_timeout_millis: int

    remote_execution_address: str | None
    remote_execution_extra_platform_properties: list[str]
    remote_execution_headers: dict[str, str]
    remote_execution_overall_deadline_secs: int
    remote_execution_rpc_concurrency: int

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
            # Process execution setup.
            process_cleanup=bootstrap_options.process_cleanup,
            local_cache=bootstrap_options.local_cache,
            process_execution_local_parallelism=bootstrap_options.process_execution_local_parallelism,
            process_execution_remote_parallelism=dynamic_remote_options.parallelism,
            process_execution_cache_namespace=bootstrap_options.process_execution_cache_namespace,
            process_execution_graceful_shutdown_timeout=bootstrap_options.process_execution_graceful_shutdown_timeout,
            process_execution_local_enable_nailgun=bootstrap_options.process_execution_local_enable_nailgun,
            process_total_child_memory_usage=bootstrap_options.process_total_child_memory_usage,
            process_per_child_memory_usage=bootstrap_options.process_per_child_memory_usage,
            # Remote store setup.
            remote_store_address=dynamic_remote_options.store_address,
            remote_store_headers=dynamic_remote_options.store_headers,
            remote_store_chunk_bytes=bootstrap_options.remote_store_chunk_bytes,
            remote_store_chunk_upload_timeout_seconds=bootstrap_options.remote_store_chunk_upload_timeout_seconds,
            remote_store_rpc_retries=bootstrap_options.remote_store_rpc_retries,
            remote_store_rpc_concurrency=dynamic_remote_options.store_rpc_concurrency,
            remote_store_batch_api_size_limit=bootstrap_options.remote_store_batch_api_size_limit,
            # Remote cache setup.
            remote_cache_eager_fetch=bootstrap_options.remote_cache_eager_fetch,
            remote_cache_warnings=bootstrap_options.remote_cache_warnings,
            remote_cache_rpc_concurrency=dynamic_remote_options.cache_rpc_concurrency,
            remote_cache_read_timeout_millis=bootstrap_options.remote_cache_read_timeout_millis,
            # Remote execution setup.
            remote_execution_address=dynamic_remote_options.execution_address,
            remote_execution_extra_platform_properties=bootstrap_options.remote_execution_extra_platform_properties,
            remote_execution_headers=dynamic_remote_options.execution_headers,
            remote_execution_overall_deadline_secs=bootstrap_options.remote_execution_overall_deadline_secs,
            remote_execution_rpc_concurrency=dynamic_remote_options.execution_rpc_concurrency,
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
    # Process execution setup.
    process_total_child_memory_usage=None,
    process_per_child_memory_usage=memory_size(_PER_CHILD_MEMORY_USAGE),
    process_execution_local_parallelism=CPU_COUNT,
    process_execution_remote_parallelism=128,
    process_execution_cache_namespace=None,
    process_cleanup=True,
    local_cache=True,
    process_execution_local_enable_nailgun=True,
    process_execution_graceful_shutdown_timeout=3,
    # Remote store setup.
    remote_store_address=None,
    remote_store_headers={
        "user-agent": f"pants/{VERSION}",
    },
    remote_store_chunk_bytes=1024 * 1024,
    remote_store_chunk_upload_timeout_seconds=60,
    remote_store_rpc_retries=2,
    remote_store_rpc_concurrency=128,
    remote_store_batch_api_size_limit=4194304,
    # Remote cache setup.
    remote_cache_eager_fetch=True,
    remote_cache_warnings=RemoteCacheWarningsBehavior.backoff,
    remote_cache_rpc_concurrency=128,
    remote_cache_read_timeout_millis=1500,
    # Remote execution setup.
    remote_execution_address=None,
    remote_execution_extra_platform_properties=[],
    remote_execution_headers={
        "user-agent": f"pants/{VERSION}",
    },
    remote_execution_overall_deadline_secs=60 * 60,  # one hour
    remote_execution_rpc_concurrency=128,
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
            "--level",
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
        "--backend-packages",
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
        "--plugins",
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
        "--plugins-force-resolve",
        advanced=True,
        default=False,
        help="Re-resolve plugins, even if previously resolved.",
    )
    level = LogLevelOption()
    show_log_target = BoolOption(
        "--show-log-target",
        default=False,
        daemon=True,
        advanced=True,
        help=softwrap(
            """
            Display the target where a log message originates in that log message's output.
            This can be helpful when paired with --log-levels-by-target.
            """
        ),
    )
    log_levels_by_target = DictOption[str](
        "--log-levels-by-target",
        daemon=True,
        advanced=True,
        help=softwrap(
            """
            Set a more specific logging level for one or more logging targets. The names of
            logging targets are specified in log strings when the --show-log-target option is set.
            The logging levels are one of: "error", "warn", "info", "debug", "trace".
            All logging targets not specified here use the global log level set with --level. For example,
            you can set `--log-levels-by-target='{"workunit_store": "info", "pants.engine.rules": "warn"}'`.
            """
        ),
    )
    log_show_rust_3rdparty = BoolOption(
        "--log-show-rust-3rdparty",
        default=False,
        daemon=True,
        advanced=True,
        help="Whether to show/hide logging done by 3rdparty Rust crates used by the Pants engine.",
    )
    ignore_warnings = StrListOption(
        "--ignore-warnings",
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
        "--pants-version",
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
        "--pants-bin-name",
        advanced=True,
        default="./pants",  # noqa: PANTSBIN
        help="The name of the script or binary used to invoke Pants. "
        "Useful when printing help messages.",
    )
    pants_workdir = StrOption(
        "--pants-workdir",
        advanced=True,
        metavar="<dir>",
        default=lambda _: os.path.join(get_buildroot(), ".pants.d"),
        daemon=True,
        help="Write intermediate logs and output files to this dir.",
    )
    pants_physical_workdir_base = StrOption(
        "--pants-physical-workdir-base",
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
        "--pants-distdir",
        advanced=True,
        metavar="<dir>",
        default=lambda _: os.path.join(get_buildroot(), "dist"),
        help="Write end products, such as the results of `./pants package`, to this dir.",  # noqa: PANTSBIN
    )
    pants_subprocessdir = StrOption(
        "--pants-subprocessdir",
        advanced=True,
        default=lambda _: os.path.join(get_buildroot(), ".pids"),
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
        "--pants-config-files",
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
        "--pantsrc",
        advanced=True,
        default=True,
        # NB: See `--pants-config-files`.
        fingerprint=False,
        help="Use pantsrc files located at the paths specified in the global option `pantsrc_files`.",
    )
    pantsrc_files = StrListOption(
        "--pantsrc-files",
        advanced=True,
        metavar="<path>",
        # NB: See `--pants-config-files`.
        fingerprint=False,
        default=["/etc/pantsrc", "~/.pants.rc", ".pants.rc"],
        help="Override config with values from these files, using syntax matching that of `--pants-config-files`.",
    )
    pythonpath = StrListOption(
        "--pythonpath",
        advanced=True,
        help=softwrap(
            """
            Add these directories to PYTHONPATH to search for plugins. This does not impact the
            PYTHONPATH used by Pants when running your Python code.
            """
        ),
    )
    spec_files = StrListOption(
        "--spec-files",
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
        "--verify-config",
        default=True,
        advanced=True,
        help="Verify that all config file values correspond to known options.",
    )
    stats_record_option_scopes = StrListOption(
        "--stats-record-option-scopes",
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
        "--pants-ignore",
        advanced=True,
        default=[".*/", _default_rel_distdir, "__pycache__"],
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
        "--pants-ignore-use-gitignore",
        advanced=True,
        default=True,
        help=softwrap(
            """
            Make use of a root .gitignore file when determining whether to ignore filesystem
            operations performed by Pants. If used together with `--pants-ignore`, any exclude/include
            patterns specified there apply after .gitignore rules.
            """
        ),
    )
    # These logging options are registered in the bootstrap phase so that plugins can log during
    # registration and not so that their values can be interpolated in configs.
    logdir = StrOption(
        "--logdir",
        advanced=True,
        default=None,
        metavar="<dir>",
        daemon=True,
        help="Write logs to files under this directory.",
    )
    pantsd = BoolOption(
        "--pantsd",
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
        "--concurrent",
        default=False,
        help=softwrap(
            """
            Enable concurrent runs of Pants. Without this enabled, Pants will
            start up all concurrent invocations (e.g. in other terminals) without pantsd.
            Enabling this option requires parallel Pants invocations to block on the first.
            """
        ),
    )

    # NB: We really don't want this option to invalidate the daemon, because different clients might have
    # different needs. For instance, an IDE might have a very long timeout because it only wants to refresh
    # a project in the background, while a user might want a shorter timeout for interactivity.
    pantsd_timeout_when_multiple_invocations = FloatOption(
        "--pantsd-timeout-when-multiple-invocations",
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
        "--pantsd-max-memory-usage",
        advanced=True,
        default=memory_size("1GiB"),
        default_help_repr="1GiB",
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
        "--print-stacktrace",
        advanced=True,
        default=False,
        help="Print the full exception stack trace for any errors.",
    )
    engine_visualize_to = DirOption(
        "--engine-visualize-to",
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
        "--pantsd-pailgun-port",
        advanced=True,
        default=0,
        daemon=True,
        help="The port to bind the Pants nailgun server to. Defaults to a random port.",
    )
    pantsd_invalidation_glob = StrListOption(
        "--pantsd-invalidation-globs",
        advanced=True,
        daemon=True,
        help=softwrap(
            """
            Filesystem events matching any of these globs will trigger a daemon restart.
            Pants's own code, plugins, and `--pants-config-files` are inherently invalidated.
            """
        ),
    )

    _rule_threads_core_flag = "--rule-threads-core"
    _process_execution_local_parallelism_flag = "--process-execution-local-parallelism"
    _rule_threads_max_flag = "--rule-threads-max"

    rule_threads_core = IntOption(
        _rule_threads_core_flag,
        default=max(2, CPU_COUNT // 2),
        default_help_repr="max(2, #cores/2)",
        advanced=True,
        help=softwrap(
            f"""
            The number of threads to keep active and ready to execute `@rule` logic (see
            also: `{_rule_threads_max_flag}`).

            Values less than 2 are not currently supported.

            This value is independent of the number of processes that may be spawned in
            parallel locally (controlled by `{_process_execution_local_parallelism_flag}`).
            """
        ),
    )
    rule_threads_max = IntOption(
        _rule_threads_max_flag,
        default=None,
        advanced=True,
        help=softwrap(
            f"""
            The maximum number of threads to use to execute `@rule` logic. Defaults to
            a small multiple of `{_rule_threads_core_flag}`.
            """
        ),
    )

    local_store_dir_flag = "--local-store-dir"
    local_store_shard_count_flag = "--local-store-shard-count"
    local_store_files_max_size_bytes_flag = "--local-store-files-max-size-bytes"
    cache_instructions = softwrap(
        """
        The path may be absolute or relative. If the directory is within the build root, be
        sure to include it in `--pants-ignore`.
        """
    )

    local_store_dir = StrOption(
        local_store_dir_flag,
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
        local_store_shard_count_flag,
        advanced=True,
        help=softwrap(
            f"""
            The number of LMDB shards created for the local store. This setting also impacts
            the maximum size of stored files: see `{local_store_files_max_size_bytes_flag}`
            for more information.

            Because LMDB allows only one simultaneous writer per database, the store is split
            into multiple shards to allow for more concurrent writers. The faster your disks
            are, the fewer shards you are likely to need for performance.

            NB: After changing this value, you will likely want to manually clear the
            `{local_store_dir_flag}` directory to clear the space used by old shard layouts.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.shard_count,
    )
    local_store_processes_max_size_bytes = IntOption(
        "--local-store-processes-max-size-bytes",
        advanced=True,
        help=softwrap(
            f"""
            The maximum size in bytes of the local store containing process cache entries.
            Stored below `{local_store_dir_flag}`.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.processes_max_size_bytes,
    )
    local_store_files_max_size_bytes = IntOption(
        local_store_files_max_size_bytes_flag,
        advanced=True,
        help=softwrap(
            f"""
            The maximum size in bytes of the local store containing files.
            Stored below `{local_store_dir_flag}`.

            NB: This size value bounds the total size of all files, but (due to sharding of the
            store on disk) it also bounds the per-file size to (VALUE /
            `{local_store_shard_count_flag}`).

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
        "--local-store-directories-max-size-bytes",
        advanced=True,
        help=softwrap(
            f"""
            The maximum size in bytes of the local store containing directories.
            Stored below `{local_store_dir_flag}`.
            """
        ),
        default=DEFAULT_LOCAL_STORE_OPTIONS.directories_max_size_bytes,
    )
    _named_caches_dir = StrOption(
        "--named-caches-dir",
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
        "--local-execution-root-dir",
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
        "--local-cache",
        default=DEFAULT_EXECUTION_OPTIONS.local_cache,
        help=softwrap(
            """
            Whether to cache process executions in a local cache persisted to disk at
            `--local-store-dir`.
            """
        ),
    )
    process_cleanup = BoolOption(
        "--process-cleanup",
        default=DEFAULT_EXECUTION_OPTIONS.process_cleanup,
        help=softwrap(
            """
            If false, Pants will not clean up local directories used as chroots for running
            processes. Pants will log their location so that you can inspect the chroot, and
            run the `__run.sh` script to recreate the process using the same argv and
            environment variables used by Pants. This option is useful for debugging.
            """
        ),
    )
    ca_certs_path = StrOption(
        "--ca-certs-path",
        advanced=True,
        default=None,
        help=softwrap(
            """
            Path to a file containing PEM-format CA certificates used for verifying secure
            connections when downloading files required by a build.
            """
        ),
    )

    _process_total_child_memory_usage = "--process-total-child-memory-usage"
    _process_per_child_memory_usage_flag = "--process-per-child-memory-usage"
    process_total_child_memory_usage = MemorySizeOption(
        _process_total_child_memory_usage,
        advanced=True,
        default=None,
        help=softwrap(
            f"""
            The maximum memory usage for all "pooled" child processes.

            When set, this value participates in precomputing the pool size of child processes
            used by Pants (pooling is currently used only for the JVM). When not set, Pants will
            default to spawning `2 * {_process_execution_local_parallelism_flag}` pooled processes.

            A high value would result in a high number of child processes spawned, potentially
            overconsuming your resources and triggering the OS' OOM killer. A low value would
            mean a low number of child processes launched and therefore less parallelism for the
            tasks that need those processes.

            If setting this value, consider also adjusting the value of the
            `{_process_per_child_memory_usage_flag}` option.

            You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g.
            `2GiB` or `2.12GiB`. A bare number will be in bytes.
            """
        ),
    )
    process_per_child_memory_usage = MemorySizeOption(
        _process_per_child_memory_usage_flag,
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.process_per_child_memory_usage,
        default_help_repr=_PER_CHILD_MEMORY_USAGE,
        help=softwrap(
            f"""
            The default memory usage for a single "pooled" child process.

            Check the documentation for the `{_process_total_child_memory_usage}` for advice on
            how to choose an appropriate value for this option.

            You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g.
            `2GiB` or `2.12GiB`. A bare number will be in bytes.
            """
        ),
    )
    process_execution_local_parallelism = IntOption(
        _process_execution_local_parallelism_flag,
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_parallelism,
        default_help_repr="#cores",
        advanced=True,
        help=softwrap(
            f"""
            Number of concurrent processes that may be executed locally.

            This value is independent of the number of threads that may be used to
            execute the logic in `@rules` (controlled by `{_rule_threads_core_flag}`).
            """
        ),
    )
    process_execution_remote_parallelism = IntOption(
        "--process-execution-remote-parallelism",
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_remote_parallelism,
        advanced=True,
        help="Number of concurrent processes that may be executed remotely.",
    )
    process_execution_cache_namespace = StrOption(
        "--process-execution-cache-namespace",
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
        "--process-execution-local-enable-nailgun",
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_enable_nailgun,
        help="Whether or not to use nailgun to run JVM requests that are marked as supporting nailgun.",
        advanced=True,
    )
    process_execution_graceful_shutdown_timeout = IntOption(
        "--process-execution-graceful-shutdown-timeout",
        default=DEFAULT_EXECUTION_OPTIONS.process_execution_graceful_shutdown_timeout,
        help=softwrap(
            f"""
            The time in seconds to wait when gracefully shutting down an interactive process (such
            as one opened using `{bin_name()} run`) before killing it.
            """
        ),
        advanced=True,
    )
    remote_execution = BoolOption(
        "--remote-execution",
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution,
        help=softwrap(
            """
            Enables remote workers for increased parallelism. (Alpha)

            Alternatively, you can use `--remote-cache-read` and `--remote-cache-write` to still run
            everything locally, but to use a remote cache.
            """
        ),
    )
    remote_cache_read = BoolOption(
        "--remote-cache-read",
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_read,
        help=softwrap(
            """
            Whether to enable reading from a remote cache.

            This cannot be used at the same time as `--remote-execution`.
            """
        ),
    )
    remote_cache_write = BoolOption(
        "--remote-cache-write",
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_write,
        help=softwrap(
            """
            Whether to enable writing results to a remote cache.

            This cannot be used at the same time as `--remote-execution`.
            """
        ),
    )
    remote_instance_name = StrOption(
        "--remote-instance-name",
        default=None,
        advanced=True,
        help=softwrap(
            """
            Name of the remote instance to use by remote caching and remote execution.

            This is used by some remote servers for routing. Consult your remote server for
            whether this should be set.

            You can also use `--remote-auth-plugin` to provide a plugin to dynamically set this value.
            """
        ),
    )
    remote_ca_certs_path = StrOption(
        "--remote-ca-certs-path",
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a PEM file containing CA certificates used for verifying secure
            connections to `--remote-execution-address` and `--remote-store-address`.

            If unspecified, Pants will attempt to auto-discover root CA certificates when TLS
            is enabled with remote execution and caching.
            """
        ),
    )
    remote_oath_bearer_token_path = StrOption(
        "--remote-oauth-bearer-token-path",
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a file containing an oauth token to use for gGRPC connections to
            `--remote-execution-address` and `--remote-store-address`.

            If specified, Pants will add a header in the format `authorization: Bearer <token>`.
            You can also manually add this header via `--remote-execution-headers` and
            `--remote-store-headers`, or use `--remote-auth-plugin` to provide a plugin to
            dynamically set the relevant headers. Otherwise, no authorization will be performed.
            """
        ),
    )
    remote_auth_plugin = StrOption(
        "--remote-auth-plugin",
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to a plugin to dynamically configure remote caching and execution options.

            Format: `path.to.module:my_func`. Pants will import your module and run your
            function. Update the `--pythonpath` option to ensure your file is loadable.

            The function should take the kwargs `initial_store_headers: dict[str, str]`,
            `initial_execution_headers: dict[str, str]`, `options: Options` (from
            pants.option.options), `env: dict[str, str]`, and
            `prior_result: AuthPluginResult | None`. It should return an instance of
            `AuthPluginResult` from `pants.option.global_options`.

            Pants will replace the headers it would normally use with whatever your plugin
            returns; usually, you should include the `initial_store_headers` and
            `initial_execution_headers` in your result so that options like
            `--remote-store-headers` still work.

            If you return `instance_name`, Pants will replace `--remote-instance-name`
            with this value.

            If the returned auth state is `AuthPluginState.UNAVAILABLE`, Pants will disable
            remote caching and execution.

            If Pantsd is in use, `prior_result` will be the previous
            `AuthPluginResult` returned by your plugin, which allows you to reuse the result.
            Otherwise, if Pantsd has been restarted or is not used, the `prior_result` will
            be `None`.
            """
        ),
    )
    remote_store_address = StrOption(
        "--remote-store-address",
        advanced=True,
        default=cast(str, DEFAULT_EXECUTION_OPTIONS.remote_store_address),
        help=softwrap(
            """
            The URI of a server used for the remote file store.

            Format: `scheme://host:port`. The supported schemes are `grpc` and `grpcs`, i.e. gRPC
            with TLS enabled. If `grpc` is used, TLS will be disabled.
            """
        ),
    )
    remote_store_headers = DictOption(
        "--remote-store-headers",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_headers,
        help=softwrap(
            """
            Headers to set on remote store requests.

            Format: header=value. Pants may add additional headers.

            See `--remote-execution-headers` as well.
            """
        ),
        default_help_repr=repr(DEFAULT_EXECUTION_OPTIONS.remote_store_headers).replace(
            VERSION, "<pants_version>"
        ),
    )
    remote_store_chunk_bytes = IntOption(
        "--remote-store-chunk-bytes",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_bytes,
        help="Size in bytes of chunks transferred to/from the remote file store.",
    )
    remote_store_chunk_upload_timeout_seconds = IntOption(
        "--remote-store-chunk-upload-timeout-seconds",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_upload_timeout_seconds,
        help="Timeout (in seconds) for uploads of individual chunks to the remote file store.",
    )
    remote_store_rpc_retries = IntOption(
        "--remote-store-rpc-retries",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_retries,
        help="Number of times to retry any RPC to the remote store before giving up.",
    )
    remote_store_rpc_concurrency = IntOption(
        "--remote-store-rpc-concurrency",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_concurrency,
        help="The number of concurrent requests allowed to the remote store service.",
    )
    remote_store_batch_api_size_limit = IntOption(
        "--remote-store-batch-api-size-limit",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_store_batch_api_size_limit,
        help="The maximum total size of blobs allowed to be sent in a single batch API call to the remote store.",
    )
    remote_cache_warnings = EnumOption(
        "--remote-cache-warnings",
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
    remote_cache_eager_fetch = BoolOption(
        "--remote-cache-eager-fetch",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_eager_fetch,
        help=softwrap(
            """
            Eagerly fetch relevant content from the remote store instead of lazily fetching.

            This may result in worse performance, but reduce the frequency of errors
            encountered by reducing the surface area of when remote caching is used.
            """
        ),
    )
    remote_cache_rpc_concurrency = IntOption(
        "--remote-cache-rpc-concurrency",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_rpc_concurrency,
        help="The number of concurrent requests allowed to the remote cache service.",
    )
    remote_cache_rwad_timeout_millis = IntOption(
        "--remote-cache-read-timeout-millis",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_cache_read_timeout_millis,
        help="Timeout value for remote cache lookups in milliseconds.",
    )
    remote_execution_address = StrOption(
        "--remote-execution-address",
        advanced=True,
        default=cast(str, DEFAULT_EXECUTION_OPTIONS.remote_execution_address),
        help=softwrap(
            """
            The URI of a server used as a remote execution scheduler.

            Format: `scheme://host:port`. The supported schemes are `grpc` and `grpcs`, i.e. gRPC
            with TLS enabled. If `grpc` is used, TLS will be disabled.

            You must also set `--remote-store-address`, which will often be the same value.
            """
        ),
    )
    remote_execution_extra_platform_properties = StrListOption(
        "--remote-execution-extra-platform-properties",
        advanced=True,
        help=softwrap(
            """
            Platform properties to set on remote execution requests.
            Format: property=value. Multiple values should be specified as multiple
            occurrences of this flag. Pants itself may add additional platform properties.
            """
        ),
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_extra_platform_properties,
    )
    remote_execution_headers = DictOption(
        "--remote-execution-headers",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_headers,
        help=softwrap(
            """
            Headers to set on remote execution requests. Format: header=value. Pants
            may add additional headers.

            See `--remote-store-headers` as well.
            """
        ),
        default_help_repr=repr(DEFAULT_EXECUTION_OPTIONS.remote_execution_headers).replace(
            VERSION, "<pants_version>"
        ),
    )
    remote_execution_overall_deadline_secs = IntOption(
        "--remote-execution-overall-deadline-secs",
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_overall_deadline_secs,
        advanced=True,
        help="Overall timeout in seconds for each remote execution request from time of submission",
    )
    remote_execution_rpc_concurrency = IntOption(
        "--remote-execution-rpc-concurrency",
        advanced=True,
        default=DEFAULT_EXECUTION_OPTIONS.remote_execution_rpc_concurrency,
        help="The number of concurrent requests allowed to the remote execution service.",
    )
    watch_filesystem = BoolOption(
        "--watch-filesystem",
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
        "--colors",
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
        "--dynamic-ui",
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
        "--dynamic-ui-renderer",
        default=DynamicUIRenderer.indicatif_spinner,
        help="If `--dynamic-ui` is enabled, selects the renderer.",
    )

    tag = StrListOption(
        "--tag",
        help=softwrap(
            f"""
            Include only targets with these tags (optional '+' prefix) or without these
            tags ('-' prefix). See {doc_url('advanced-target-selection')}.
            """
        ),
        metavar="[+-]tag1,tag2,...",
    )
    exclude_target_regexp = StrListOption(
        "--exclude-target-regexp",
        help="Exclude targets that match these regexes. This does not impact file arguments.",
        metavar="<regexp>",
        removal_version="2.14.0.dev0",
        removal_hint=softwrap(
            """
            Use the option `--filter-address-regex` instead, with `-` in front of the regex. For
            example, `--exclude-target-regexp=dir/` should become `--filter-address-regex=-dir/`.

            The `--filter` options can now be used with any goal, not only the `filter` goal,
            so there is no need for this option anymore.
            """
        ),
    )

    files_not_found_behavior = EnumOption(
        "--files-not-found-behavior",
        default=UnmatchedBuildFileGlobs.warn,
        help=softwrap(
            """
            What to do when files and globs specified in BUILD files, such as in the
            `sources` field, cannot be found. This happens when the files do not exist on
            your machine or when they are ignored by the `--pants-ignore` option.
            """
        ),
        advanced=True,
        removal_version="2.14.0.dev0",
        removal_hint=softwrap(
            """
            Use `[GLOBAL].unmatched_build_file_globs` instead, which behaves the same. This
            option was renamed for clarity with the new `[GLOBAL].unmatched_cli_globs` option.
            """
        ),
    )
    unmatched_build_file_globs = EnumOption(
        "--unmatched-build-file-globs",
        default=UnmatchedBuildFileGlobs.warn,
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
        "--unmatched-cli-globs",
        default=UnmatchedCliGlobs.error,
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

    owners_not_found_behavior = EnumOption(
        "--owners-not-found-behavior",
        default=OwnersNotFoundBehavior.ignore,
        help=softwrap(
            """
            What to do when file arguments do not have any owning target. This happens when
            there are no targets whose `sources` fields include the file argument.
            """
        ),
        advanced=True,
        removal_version="2.14.0.dev0",
        removal_hint=softwrap(
            """
            This option is no longer useful with Pants because we have goals that work without any
            targets, e.g. the `count-loc` goal or the `regex-lint` linter from the `lint` goal. This
            option caused us to error on valid use cases.

            For goals that require targets, like `list`, the unowned file will simply be ignored. If
            no owners are found at all, most goals will warn and some like `run` will error.
            """
        ),
    )

    build_patterns = StrListOption(
        "--build-patterns",
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
        "--build-ignore",
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
        "--build-file-prelude-globs",
        help=softwrap(
            f"""
            Python files to evaluate and whose symbols should be exposed to all BUILD files.
            See {doc_url('macros')}.
            """
        ),
        advanced=True,
    )
    subproject_roots = StrListOption(
        "--subproject-roots",
        help="Paths that correspond with build roots for any subproject that this project depends on.",
        advanced=True,
    )

    _loop_flag = "--loop"
    loop = BoolOption(
        _loop_flag, default=False, help="Run goals continuously as file changes are detected."
    )
    loop_max = IntOption(
        "--loop-max",
        default=2**32,
        help=f"The maximum number of times to loop when `{_loop_flag}` is specified.",
        advanced=True,
    )

    streaming_workunits_report_interval = FloatOption(
        "--streaming-workunits-report-interval",
        default=1.0,
        help="Interval in seconds between when streaming workunit event receivers will be polled.",
        advanced=True,
    )
    streaming_workunits_level = EnumOption(
        "--streaming-workunits-level",
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
        "--streaming-workunits-complete-async",
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

    use_deprecated_directory_cli_args_semantics = BoolOption(
        "--use-deprecated-directory-cli-args-semantics",
        default=True,
        help=softwrap(
            f"""
            If true, Pants will use the old, deprecated semantics for directory arguments like
            `{bin_name()} test dir`: directories are shorthand for the target `dir:dir`, i.e. the
            target that leaves off `name=`.

            If false, Pants will use the new semantics: directory arguments will match all files
            and targets in the directory, e.g. `{bin_name()} test dir` will run all tests in `dir`.

            The new semantics will become the default in Pants 2.14, and the old semantics will be
            removed in 2.15.

            This also impacts the behavior of the `tailor` goal. If this option is true,
            `{bin_name()} tailor` without additional arguments will run over the whole project, and
            `{bin_name()} tailor dir` will run over `dir` and all recursive sub-directories. If
            false, you must specify arguments, like `{bin_name()} tailor ::` to run over the
            whole project; specifying a directory will only add targets for that directory.
            """
        ),
    )

    _use_deprecated_pex_binary_run_semantics = BoolOption(
        "--use-deprecated-pex-binary-run-semantics",
        default=True,
        help=softwrap(
            """
            If `true`, `run`ning a `pex_binary` will run your firstparty code by copying sources to
            a sandbox (while still using a PEX for thirdparty dependencies). Additionally, you can
            refer to the `pex_binary` using the value of its `entry_point` field (if it is a filename).

            If `false`, `run`ning a `pex_binary` will build the PEX via `package` and run it directly.
            This makes `run` equivalent to using `package` and running the artifact. Additionally,
            the binary must be `run` using the `pex_binary`'s address, as passing a filename to `run`
            will run the `python_source`.

            Note that support has been added to Pants to allow you to `run` any `python_source`,
            so setting this to `true` should be reserved for maintaining backwards-compatibility
            with previous versions of Pants. Additionally, you can remove any `pex_binary` targets
            that exist solely for running Python code (and aren't meant to be packaged).
            """
        ),
    )

    @property
    def use_deprecated_pex_binary_run_semantics(self) -> bool:
        if self.options.is_default("use_deprecated_pex_binary_run_semantics"):
            warn_or_error(
                "2.14.0.dev1",
                "the option --use-deprecated-pex-binary-run-semantics defaulting to true",
                softwrap(
                    f"""
                    Currently, running a `pex_binary` by default will not include the source files
                    in the PEX, and will instead put them in a temporary sandbox.

                    In Pants 2.14, the default will change to instead build the PEX like you had run
                    the `package` goal, and then execute that PEX. This is more consistent and
                    intuitive behavior.

                    To fix this deprecation, explictly set `use_deprecated_pex_binary_run_semantics`
                    in the `[GLOBAL]` section of `pants.toml`.
                    Set it to `true` to use the "old" behavior.
                    Set it to `false` to use the "new" behavior.

                    When set to `false`, you can still run the binary as before because you can now
                    run on a `python_source` target. The simplest way to do this is to use
                    `{bin_name()} run path/to/file.py`, which will find the owning `python_source`.
                    Pants will run the file the same way it used to with `pex_binary` targets.
                    """
                ),
            )
        return self._use_deprecated_pex_binary_run_semantics

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
                "--rule-threads-core values less than 2 are not supported, but it was set to "
                f"{opts.rule_threads_core}."
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

        if opts.remote_execution and (opts.remote_cache_read or opts.remote_cache_write):
            raise OptionsError(
                softwrap(
                    """
                    `--remote-execution` cannot be set at the same time as either
                    `--remote-cache-read` or `--remote-cache-write`.

                    If remote execution is enabled, it will already use remote caching.
                    """
                )
            )

        if opts.remote_execution and not opts.remote_execution_address:
            raise OptionsError(
                "The `--remote-execution` option requires also setting "
                "`--remote-execution-address` to work properly."
            )
        if opts.remote_execution_address and not opts.remote_store_address:
            raise OptionsError(
                "The `--remote-execution-address` option requires also setting "
                "`--remote-store-address`. Often these have the same value."
            )

        if opts.remote_cache_read and not opts.remote_store_address:
            raise OptionsError(
                "The `--remote-cache-read` option requires also setting "
                "`--remote-store-address` to work properly."
            )
        if opts.remote_cache_write and not opts.remote_store_address:
            raise OptionsError(
                "The `--remote-cache-write` option requires also setting "
                "`--remote-store-address` or to work properly."
            )

        if not opts.watch_filesystem and (opts.pantsd or opts.loop):
            raise OptionsError(
                "The `--no-watch-filesystem` option may not be set if "
                "`--pantsd` or `--loop` is set."
            )

        def validate_remote_address(opt_name: str) -> None:
            valid_schemes = [f"{scheme}://" for scheme in ("grpc", "grpcs")]
            address = getattr(opts, opt_name)
            if address and not any(address.startswith(scheme) for scheme in valid_schemes):
                raise OptionsError(
                    f"The `{opt_name}` option must begin with one of {valid_schemes}, but "
                    f"was {address}."
                )

        validate_remote_address("remote_execution_address")
        validate_remote_address("remote_store_address")

        # Ensure that remote headers are ASCII.
        def validate_remote_headers(opt_name: str) -> None:
            command_line_opt_name = f"--{opt_name.replace('_', '-')}"
            for k, v in getattr(opts, opt_name).items():
                if not k.isascii():
                    raise OptionsError(
                        f"All values in `{command_line_opt_name}` must be ASCII, but the key "
                        f"in `{k}: {v}` has non-ASCII characters."
                    )
                if not v.isascii():
                    raise OptionsError(
                        f"All values in `{command_line_opt_name}` must be ASCII, but the value in "
                        f"`{k}: {v}` has non-ASCII characters."
                    )

        validate_remote_headers("remote_execution_headers")
        validate_remote_headers("remote_store_headers")

        illegal_build_ignores = [i for i in opts.build_ignore if i.startswith("!")]
        if illegal_build_ignores:
            raise OptionsError(
                "The `--build-ignore` option does not support negated globs, but was "
                f"given: {illegal_build_ignores}."
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


@dataclass(frozen=True)
class UseDeprecatedPexBinaryRunSemanticsOption:
    """A wrapper around the global option `use_deprecated_pex_binary_run_semantics`.

    Prefer to use this rather than requesting `GlobalOptions` for more precise invalidation.
    """

    val: bool
