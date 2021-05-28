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
from pathlib import Path
from typing import Any, Dict, List, Tuple, cast

from pants.base.build_environment import (
    get_buildroot,
    get_default_pants_config_file,
    get_pants_cachedir,
    pants_version,
)
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.native_engine import PyExecutor
from pants.option.custom_types import dir_option
from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE
from pants.option.subsystem import Subsystem
from pants.util.dirutil import fast_relpath_optional
from pants.util.docutil import bracketed_docs_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.osutil import CPU_COUNT

logger = logging.getLogger(__name__)


# The time that leases are acquired for in the local store. Configured on the Python side
# in order to ease interaction with the StoreGCService, which needs to be aware of its value.
LOCAL_STORE_LEASE_TIME_SECS = 2 * 60 * 60


MEGABYTES = 1_000_000
GIGABYTES = 1_000 * MEGABYTES


class GlobMatchErrorBehavior(Enum):
    """Describe the action to perform when matching globs in BUILD files to source files.

    NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need to
    be aware of any changes to this object's definition.
    """

    ignore = "ignore"
    warn = "warn"
    error = "error"


class FilesNotFoundBehavior(Enum):
    """What to do when globs do not match in BUILD files."""

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

    process_execution_local_cache: bool
    process_execution_local_cleanup: bool
    process_execution_local_parallelism: int
    process_execution_remote_parallelism: int
    process_execution_cache_namespace: str | None

    remote_store_address: str | None
    remote_store_headers: dict[str, str]
    remote_store_chunk_bytes: Any
    remote_store_chunk_upload_timeout_seconds: int
    remote_store_rpc_retries: int

    remote_cache_eager_fetch: bool
    remote_cache_warnings: RemoteCacheWarningsBehavior

    remote_execution_address: str | None
    remote_execution_extra_platform_properties: List[str]
    remote_execution_headers: Dict[str, str]
    remote_execution_overall_deadline_secs: int

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
            process_execution_local_cache=bootstrap_options.process_execution_local_cache,
            process_execution_local_parallelism=bootstrap_options.process_execution_local_parallelism,
            process_execution_remote_parallelism=bootstrap_options.process_execution_remote_parallelism,
            process_execution_local_cleanup=bootstrap_options.process_execution_local_cleanup,
            process_execution_cache_namespace=bootstrap_options.process_execution_cache_namespace,
            # Remote store setup.
            remote_store_address=dynamic_remote_options.store_address,
            remote_store_headers=dynamic_remote_options.store_headers,
            remote_store_chunk_bytes=bootstrap_options.remote_store_chunk_bytes,
            remote_store_chunk_upload_timeout_seconds=bootstrap_options.remote_store_chunk_upload_timeout_seconds,
            remote_store_rpc_retries=bootstrap_options.remote_store_rpc_retries,
            # Remote cache setup.
            remote_cache_eager_fetch=bootstrap_options.remote_cache_eager_fetch,
            remote_cache_warnings=bootstrap_options.remote_cache_warnings,
            # Remote execution setup.
            remote_execution_address=dynamic_remote_options.execution_address,
            remote_execution_extra_platform_properties=bootstrap_options.remote_execution_extra_platform_properties,
            remote_execution_headers=dynamic_remote_options.execution_headers,
            remote_execution_overall_deadline_secs=bootstrap_options.remote_execution_overall_deadline_secs,
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


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions(
    # Remote execution strategy.
    remote_execution=False,
    remote_cache_read=False,
    remote_cache_write=False,
    # General remote setup.
    remote_instance_name=None,
    remote_ca_certs_path=None,
    # Process execution setup.
    process_execution_local_parallelism=CPU_COUNT,
    process_execution_remote_parallelism=128,
    process_execution_cache_namespace=None,
    process_execution_local_cleanup=True,
    process_execution_local_cache=True,
    # Remote store setup.
    remote_store_address=None,
    remote_store_headers={},
    remote_store_chunk_bytes=1024 * 1024,
    remote_store_chunk_upload_timeout_seconds=60,
    remote_store_rpc_retries=2,
    # Remote cache setup.
    remote_cache_eager_fetch=True,
    remote_cache_warnings=RemoteCacheWarningsBehavior.first_only,
    # Remote execution setup.
    remote_execution_address=None,
    remote_execution_extra_platform_properties=[],
    remote_execution_headers={},
    remote_execution_overall_deadline_secs=60 * 60,  # one hour
)

DEFAULT_LOCAL_STORE_OPTIONS = LocalStoreOptions()


class GlobalOptions(Subsystem):
    options_scope = GLOBAL_SCOPE
    help = "Options to control the overall behavior of Pants."

    @classmethod
    def register_bootstrap_options(cls, register):
        """Register bootstrap options.

        "Bootstrap options" are the set of options necessary to create a Scheduler. If an option is
        not consumed during creation of a Scheduler, it should be in `register_options` instead.

        Bootstrap option values can be interpolated into the config file, and can be referenced
        programmatically in registration code, e.g., as register.bootstrap.pants_workdir.

        Note that regular code can also access these options as normal global-scope options. Their
        status as "bootstrap options" is only pertinent during option registration.
        """
        buildroot = get_buildroot()
        default_distdir_name = "dist"
        default_rel_distdir = f"/{default_distdir_name}/"

        register(
            "--backend-packages",
            advanced=True,
            type=list,
            default=[],
            help=(
                "Register functionality from these backends.\n\nThe backend packages must be "
                "present on the PYTHONPATH, typically because they are in the Pants core dist, in a "
                "plugin dist, or available as sources in the repo."
            ),
        )
        register(
            "--plugins",
            advanced=True,
            type=list,
            help=(
                "Allow backends to be loaded from these plugins (usually released through PyPI). "
                "The default backends for each plugin will be loaded automatically. Other backends "
                "in a plugin can be loaded by listing them in `backend_packages` in the "
                "`[GLOBAL]` scope."
            ),
        )
        register(
            "--plugins-force-resolve",
            advanced=True,
            type=bool,
            default=False,
            help="Re-resolve plugins, even if previously resolved.",
        )

        register(
            "-l",
            "--level",
            type=LogLevel,
            default=LogLevel.INFO,
            daemon=True,
            help="Set the logging level.",
        )
        register(
            "--show-log-target",
            type=bool,
            default=False,
            daemon=True,
            advanced=True,
            help="Display the target where a log message originates in that log message's output. "
            "This can be helpful when paired with --log-levels-by-target.",
        )

        register(
            "--log-levels-by-target",
            type=dict,
            default={},
            daemon=True,
            advanced=True,
            help="Set a more specific logging level for one or more logging targets. The names of "
            "logging targets are specified in log strings when the --show-log-target option is set. "
            "The logging levels are one of: "
            '"error", "warn", "info", "debug", "trace". '
            "All logging targets not specified here use the global log level set with --level. For example, "
            'you can set `--log-levels-by-target=\'{"workunit_store": "info", "pants.engine.rules": "warn"}\'`.',
        )

        register(
            "--log-show-rust-3rdparty",
            type=bool,
            default=False,
            daemon=True,
            advanced=True,
            help="Whether to show/hide logging done by 3rdparty Rust crates used by the Pants "
            "engine.",
        )

        register(
            "--colors",
            type=bool,
            default=sys.stdout.isatty(),
            help=(
                "Whether Pants should use colors in output or not. This may also impact whether "
                "some tools Pants run use color."
            ),
        )

        register(
            "--ignore-warnings",
            type=list,
            member_type=str,
            default=[],
            daemon=True,
            advanced=True,
            help=(
                "Ignore logs and warnings matching these strings.\n\n"
                "Normally, Pants will look for literal matches from the start of the log/warning "
                "message, but you can prefix the ignore with `$regex$` for Pants to instead treat "
                "your string as a regex pattern. For example:\n\n"
                "  ignore_warnings = [\n"
                "    \"DEPRECATED: option 'config' in scope 'flake8' will be removed\",\n"
                "    '$regex$:No files\\s*'\n"
                "  ]"
            ),
        )
        register(
            "--ignore-pants-warnings",
            type=list,
            member_type=str,
            default=[],
            daemon=True,
            advanced=True,
            help="Regexps matching warning strings to ignore, e.g. "
            '["DEPRECATED: the option `--my-opt` will be removed"]. The regex patterns will be '
            "matched from the start of the warning string, and are case-insensitive.",
            removal_version="2.6.0.dev0",
            removal_hint=(
                "Use the global option `--ignore-warnings` instead.\n\nUnlike this option, "
                "`--ignore-warnings` uses literal string matches instead of regex patterns by "
                "default. If you would still like to use a regex pattern, prefix the string with "
                "`$regex$`."
            ),
        )

        register(
            "--pants-version",
            advanced=True,
            default=pants_version(),
            daemon=True,
            help="Use this Pants version. Note that Pants only uses this to verify that you are "
            "using the requested version, as Pants cannot dynamically change the version it "
            "is using once the program is already running.\n\nIf you use the `./pants` script from "
            f"{bracketed_docs_url('installation')}, however, changing the value in your "
            "`pants.toml` will cause the new version to be installed and run automatically.\n\n"
            "Run `./pants --version` to check what is being used.",
        )
        register(
            "--pants-bin-name",
            advanced=True,
            default="./pants",
            help="The name of the script or binary used to invoke Pants. "
            "Useful when printing help messages.",
        )

        register(
            "--pants-workdir",
            advanced=True,
            metavar="<dir>",
            default=os.path.join(buildroot, ".pants.d"),
            daemon=True,
            help="Write intermediate logs and output files to this dir.",
        )
        register(
            "--pants-physical-workdir-base",
            advanced=True,
            metavar="<dir>",
            default=None,
            daemon=True,
            help="When set, a base directory in which to store `--pants-workdir` contents. "
            "If this option is a set, the workdir will be created as symlink into a "
            "per-workspace subdirectory.",
        )
        register(
            "--pants-supportdir",
            advanced=True,
            metavar="<dir>",
            default=os.path.join(buildroot, "build-support"),
            help="Unused. Will be deprecated in 2.2.0.",
        )
        register(
            "--pants-distdir",
            advanced=True,
            metavar="<dir>",
            default=os.path.join(buildroot, "dist"),
            help="Write end products, such as the results of `./pants package`, to this dir.",
        )
        register(
            "--pants-subprocessdir",
            advanced=True,
            default=os.path.join(buildroot, ".pids"),
            daemon=True,
            help="The directory to use for tracking subprocess metadata. This should "
            "live outside of the dir used by `pants_workdir` to allow for tracking "
            "subprocesses that outlive the workdir data.",
        )
        register(
            "--pants-config-files",
            advanced=True,
            type=list,
            # NB: We don't fingerprint the list of config files, because the content of the config
            # files independently affects fingerprints.
            fingerprint=False,
            default=[get_default_pants_config_file()],
            help=(
                "Paths to Pants config files. This may only be set through the environment variable "
                "`PANTS_CONFIG_FILES` and the command line argument `--pants-config-files`; it will "
                "be ignored if in a config file like `pants.toml`."
            ),
        )
        register(
            "--pantsrc",
            advanced=True,
            type=bool,
            default=True,
            # NB: See `--pants-config-files`.
            fingerprint=False,
            help=(
                "Use pantsrc files located at the paths specified in the global option "
                "`pantsrc_files`."
            ),
        )
        register(
            "--pantsrc-files",
            advanced=True,
            type=list,
            metavar="<path>",
            # NB: See `--pants-config-files`.
            fingerprint=False,
            default=["/etc/pantsrc", "~/.pants.rc"],
            help=(
                "Override config with values from these files, using syntax matching that of "
                "`--pants-config-files`."
            ),
        )
        register(
            "--pythonpath",
            advanced=True,
            type=list,
            help=(
                "Add these directories to PYTHONPATH to search for plugins. This does not impact "
                "the PYTHONPATH used by Pants when running your Python code."
            ),
        )
        register(
            "--spec-files",
            type=list,
            # NB: We don't fingerprint spec files because the content of the files independently
            # affects fingerprints.
            fingerprint=False,
            help=(
                "Read additional specs (target addresses, files, and/or globs), one per line,"
                "from these files."
            ),
        )
        register(
            "--verify-config",
            type=bool,
            default=True,
            advanced=True,
            help="Verify that all config file values correspond to known options.",
        )

        register(
            "--stats-record-option-scopes",
            advanced=True,
            type=list,
            default=["*"],
            help=(
                "Option scopes to record in stats on run completion. "
                "Options may be selected by joining the scope and the option with a ^ character, "
                "i.e. to get option `pantsd` in the GLOBAL scope, you'd pass `GLOBAL^pantsd`. "
                "Add a '*' to the list to capture all known scopes."
            ),
        )

        register(
            "--pants-ignore",
            advanced=True,
            type=list,
            member_type=str,
            default=[".*/", default_rel_distdir],
            help="Paths to ignore for all filesystem operations performed by pants "
            "(e.g. BUILD file scanning, glob matching, etc). "
            "Patterns use the gitignore syntax (https://git-scm.com/docs/gitignore). "
            "The `pants_distdir` and `pants_workdir` locations are automatically ignored. "
            "`pants_ignore` can be used in tandem with `pants_ignore_use_gitignore`; any rules "
            "specified here are applied after rules specified in a .gitignore file.",
        )
        register(
            "--pants-ignore-use-gitignore",
            advanced=True,
            type=bool,
            default=True,
            help="Make use of a root .gitignore file when determining whether to ignore filesystem "
            "operations performed by Pants. If used together with `--pants-ignore`, any exclude/include "
            "patterns specified there apply after .gitignore rules.",
        )

        # These logging options are registered in the bootstrap phase so that plugins can log during
        # registration and not so that their values can be interpolated in configs.
        register(
            "-d",
            "--logdir",
            advanced=True,
            metavar="<dir>",
            daemon=True,
            help="Write logs to files under this directory.",
        )

        register(
            "--pantsd",
            advanced=True,
            type=bool,
            default=True,
            daemon=True,
            help=(
                "Enables use of the Pants daemon (pantsd). pantsd can significantly improve "
                "runtime performance by lowering per-run startup cost, and by memoizing filesystem "
                "operations and rule execution."
            ),
        )

        # Whether or not to make necessary arrangements to have concurrent runs in pants.
        # In practice, this means that if this is set, a run will not even try to use pantsd.
        # NB: Eventually, we would like to deprecate this flag in favor of making pantsd runs parallelizable.
        register(
            "--concurrent",
            advanced=True,
            type=bool,
            default=False,
            help="Enable concurrent runs of Pants. Without this enabled, Pants will "
            "start up all concurrent invocations (e.g. in other terminals) without pantsd. "
            "Enabling this option requires parallel Pants invocations to block on the first",
        )

        # NB: We really don't want this option to invalidate the daemon, because different clients might have
        # different needs. For instance, an IDE might have a very long timeout because it only wants to refresh
        # a project in the background, while a user might want a shorter timeout for interactivity.
        register(
            "--pantsd-timeout-when-multiple-invocations",
            advanced=True,
            type=float,
            default=60.0,
            help="The maximum amount of time to wait for the invocation to start until "
            "raising a timeout exception. "
            "Because pantsd currently does not support parallel runs, "
            "any prior running Pants command must be finished for the current one to start. "
            "To never timeout, use the value -1.",
        )
        register(
            "--pantsd-max-memory-usage",
            advanced=True,
            type=int,
            default=2 ** 30,
            help=(
                "The maximum memory usage of the pantsd process (in bytes).\n\n"
                "When the maximum memory is exceeded, the daemon will restart gracefully, "
                "although all previous in-memory caching will be lost. Setting too low means that "
                "you may miss out on some caching, whereas setting too high may over-consume "
                "resources and may result in the operating system killing Pantsd due to memory "
                "overconsumption (e.g. via the OOM killer).\n\n"
                "There is at most one pantsd process per workspace."
            ),
        )

        # These facilitate configuring the native engine.
        register(
            "--print-stacktrace",
            advanced=True,
            type=bool,
            default=False,
            help="Print the full exception stack trace for any errors.",
        )
        register(
            "--native-engine-visualize-to",
            advanced=True,
            default=None,
            type=dir_option,
            help="A directory to write execution and rule graphs to as `dot` files. The contents "
            "of the directory will be overwritten if any filenames collide.",
        )

        # Pants Daemon options.
        register(
            "--pantsd-pailgun-port",
            advanced=True,
            type=int,
            default=0,
            daemon=True,
            help="The port to bind the Pants nailgun server to. Defaults to a random port.",
        )
        register(
            "--pantsd-invalidation-globs",
            advanced=True,
            type=list,
            default=[],
            daemon=True,
            help="Filesystem events matching any of these globs will trigger a daemon restart. "
            "Pants's own code, plugins, and `--pants-config-files` are inherently invalidated.",
        )

        process_execution_local_parallelism = "--process-execution-local-parallelism"
        rule_threads_core = "--rule-threads-core"
        rule_threads_max = "--rule-threads-max"

        register(
            rule_threads_core,
            type=int,
            default=max(2, CPU_COUNT // 2),
            advanced=True,
            help=(
                "The number of threads to keep active and ready to execute `@rule` logic (see "
                f"also: `{rule_threads_max}`).\n\nValues less than 2 are not currently supported. "
                "\n\nDefaults to half the number of cores on your machine.\n\nThis value is "
                "independent of the number of processes that may be spawned in "
                f"parallel locally (controlled by `{process_execution_local_parallelism}`)."
            ),
        )
        register(
            rule_threads_max,
            type=int,
            default=None,
            advanced=True,
            help=(
                "The maximum number of threads to use to execute `@rule` logic. Defaults to "
                f"a small multiple of `{rule_threads_core}`."
            ),
        )

        local_store_dir_flag = "--local-store-dir"
        local_store_shard_count_flag = "--local-store-shard-count"
        local_store_files_max_size_bytes_flag = "--local-store-files-max-size-bytes"
        cache_instructions = (
            "The path may be absolute or relative. If the directory is within the build root, be "
            "sure to include it in `--pants-ignore`."
        )
        register(
            local_store_dir_flag,
            advanced=True,
            help=(
                f"Directory to use for the local file store, which stores the results of "
                f"subprocesses run by Pants.\n\n{cache_instructions}"
            ),
            # This default is also hard-coded into the engine's rust code in
            # fs::Store::default_path so that tools using a Store outside of pants
            # are likely to be able to use the same storage location.
            default=DEFAULT_LOCAL_STORE_OPTIONS.store_dir,
        )
        register(
            "--local-store-shard-count",
            type=int,
            advanced=True,
            help=(
                "The number of LMDB shards created for the local store. This setting also impacts "
                f"the maximum size of stored files: see `{local_store_files_max_size_bytes_flag}` "
                "for more information."
                "\n\n"
                "Because LMDB allows only one simultaneous writer per database, the store is split "
                "into multiple shards to allow for more concurrent writers. The faster your disks "
                "are, the fewer shards you are likely to need for performance."
                "\n\n"
                "NB: After changing this value, you will likely want to manually clear the "
                f"`{local_store_dir_flag}` directory to clear the space used by old shard layouts."
            ),
            default=DEFAULT_LOCAL_STORE_OPTIONS.shard_count,
        )
        register(
            "--local-store-processes-max-size-bytes",
            type=int,
            advanced=True,
            help=(
                "The maximum size in bytes of the local store containing process cache entries. "
                f"Stored below `{local_store_dir_flag}`."
            ),
            default=DEFAULT_LOCAL_STORE_OPTIONS.processes_max_size_bytes,
        )
        register(
            local_store_files_max_size_bytes_flag,
            type=int,
            advanced=True,
            help=(
                "The maximum size in bytes of the local store containing files. "
                f"Stored below `{local_store_dir_flag}`."
                "\n\n"
                "NB: This size value bounds the total size of all files, but (due to sharding of the "
                "store on disk) it also bounds the per-file size to (VALUE / "
                f"`{local_store_shard_count_flag}`)."
                "\n\n"
                "This value doesn't reflect space allocated on disk, or RAM allocated (it "
                "may be reflected in VIRT but not RSS). However, the default is lower than you "
                "might otherwise choose because macOS creates core dumps that include MMAP'd "
                "pages, and setting this too high might cause core dumps to use an unreasonable "
                "amount of disk if they are enabled."
            ),
            default=DEFAULT_LOCAL_STORE_OPTIONS.files_max_size_bytes,
        )
        register(
            "--local-store-directories-max-size-bytes",
            type=int,
            advanced=True,
            help=(
                "The maximum size in bytes of the local store containing directories. "
                f"Stored below `{local_store_dir_flag}`."
            ),
            default=DEFAULT_LOCAL_STORE_OPTIONS.directories_max_size_bytes,
        )
        register(
            "--named-caches-dir",
            advanced=True,
            help=(
                "Directory to use for named global caches for tools and processes with trusted, "
                f"concurrency-safe caches.\n\n{cache_instructions}"
            ),
            default=os.path.join(get_pants_cachedir(), "named_caches"),
        )

        register(
            "--local-execution-root-dir",
            advanced=True,
            help=(
                f"Directory to use for local process execution sandboxing.\n\n{cache_instructions}"
            ),
            default=tempfile.gettempdir(),
        )
        register(
            "--process-execution-local-cache",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_cache,
            advanced=True,
            help=(
                "Whether to cache process executions in a local cache persisted to disk at "
                "`--local-store-dir`."
            ),
        )
        register(
            "--process-execution-local-cleanup",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_cleanup,
            advanced=True,
            help=(
                "If false, Pants will not clean up local directories used as chroots for running "
                "processes. Pants will log their location so that you can inspect the chroot, and "
                "run the `__run.sh` script to recreate the process using the same argv and "
                "environment variables used by Pants. This option is useful for debugging."
            ),
        )

        register(
            "--ca-certs-path",
            advanced=True,
            type=str,
            default=None,
            help="Path to a file containing PEM-format CA certificates used for verifying secure "
            "connections when downloading files required by a build.",
        )

        register(
            process_execution_local_parallelism,
            type=int,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_parallelism,
            advanced=True,
            help=(
                "Number of concurrent processes that may be executed locally.\n\n"
                "Defaults to the number of cores on your machine.\n\nThis value is independent of "
                "the number of threads that may be used to execute the logic in `@rules` "
                f"(controlled by `{rule_threads_core}`)."
            ),
        )
        register(
            "--process-execution-remote-parallelism",
            type=int,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_remote_parallelism,
            advanced=True,
            help="Number of concurrent processes that may be executed remotely.",
        )
        register(
            "--process-execution-cache-namespace",
            advanced=True,
            type=str,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_cache_namespace,
            help=(
                "The cache namespace for process execution. "
                "Change this value to invalidate every artifact's execution, or to prevent "
                "process cache entries from being (re)used for different usecases or users."
            ),
        )

        register(
            "--remote-execution",
            advanced=True,
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.remote_execution,
            help=(
                "Enables remote workers for increased parallelism. (Alpha)\n\nAlternatively, you "
                "can use `--remote-cache-read` and `--remote-cache-write` to still run everything "
                "locally, but to use a remote cache."
            ),
        )
        register(
            "--remote-cache-read",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.remote_cache_read,
            advanced=True,
            help=(
                "Whether to enable reading from a remote cache.\n\nThis cannot be used at the same "
                "time as `--remote-execution`."
            ),
        )
        register(
            "--remote-cache-write",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.remote_cache_write,
            advanced=True,
            help=(
                "Whether to enable writing results to a remote cache.\n\nThis cannot be used at "
                "the same time as `--remote-execution`."
            ),
        )

        register(
            "--remote-instance-name",
            advanced=True,
            help=(
                "Name of the remote instance to use by remote caching and remote execution.\n\n"
                "This is used by some remote servers for routing. Consult your remote server for "
                "whether this should be set.\n\nYou can also use `--remote-auth-plugin` to provide "
                "a plugin to dynamically set this value."
            ),
        )
        register(
            "--remote-ca-certs-path",
            advanced=True,
            help=(
                "Path to a PEM file containing CA certificates used for verifying secure "
                "connections to --remote-execution-address and --remote-store-address.\n\nIf "
                "unspecified, Pants will attempt to auto-discover root CA certificates when TLS "
                "is enabled with remote execution and caching."
            ),
        )
        register(
            "--remote-oauth-bearer-token-path",
            advanced=True,
            help=(
                "Path to a file containing an oauth token to use for gGRPC connections to "
                "--remote-execution-address and --remote-store-address.\n\nIf specified, Pants will "
                "add a header in the format `authorization: Bearer <token>`. You can also manually "
                "add this header via `--remote-execution-headers` and `--remote-store-headers`, or "
                "use `--remote-auth-plugin` to provide a plugin to dynamically set the relevant "
                "headers. Otherwise, no authorization will be performed."
            ),
        )
        register(
            "--remote-auth-plugin",
            advanced=True,
            type=str,
            default=None,
            help=(
                "Path to a plugin to dynamically configure remote caching and execution "
                "options.\n\n"
                "Format: `path.to.module:my_func`. Pants will import your module and run your "
                "function. Update the `--pythonpath` option to ensure your file is loadable.\n\n"
                "The function should take the kwargs `initial_store_headers: dict[str, str]`, "
                "`initial_execution_headers: dict[str, str]`, `options: Options` (from "
                "pants.option.options), `env: dict[str, str]`, and "
                "`prior_result: AuthPluginResult | None`. It should return an instance of "
                "`AuthPluginResult` from `pants.option.global_options`.\n\n"
                "Pants will replace the headers it would normally use with whatever your plugin "
                "returns; usually, you should include the `initial_store_headers` and "
                "`initial_execution_headers` in your result so that options like "
                "`--remote-store-headers` still work.\n\n"
                "If you return `instance_name`, Pants will replace `--remote-instance-name` "
                "with this value.\n\n"
                "If the returned auth state is AuthPluginState.UNAVAILABLE, Pants will disable "
                "remote caching and execution.\n\n"
                "If Pantsd is in use, `prior_result` will be the previous "
                "`AuthPluginResult` returned by your plugin, which allows you to reuse the result. "
                "Otherwise, if Pantsd has been restarted or is not used, the `prior_result` will "
                "be `None`."
            ),
        )

        register(
            "--remote-store-address",
            advanced=True,
            type=str,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_address,
            help=(
                "The URI of a server used for the remote file store.\n\nFormat: "
                "`scheme://host:port`. The supported schemes are `grpc` and `grpcs`, i.e. gRPC "
                "with TLS enabled. If `grpc` is used, TLS will be disabled."
            ),
        )
        register(
            "--remote-store-headers",
            advanced=True,
            type=dict,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_headers,
            help=(
                "Headers to set on remote store requests.\n\nFormat: header=value. Pants "
                "may add additional headers.\n\nSee `--remote-execution-headers` as well."
            ),
        )
        register(
            "--remote-store-chunk-bytes",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_bytes,
            help="Size in bytes of chunks transferred to/from the remote file store.",
        )
        register(
            "--remote-store-chunk-upload-timeout-seconds",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_chunk_upload_timeout_seconds,
            help="Timeout (in seconds) for uploads of individual chunks to the remote file store.",
        )
        register(
            "--remote-store-rpc-retries",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_rpc_retries,
            help="Number of times to retry any RPC to the remote store before giving up.",
        )

        register(
            "--remote-cache-warnings",
            type=RemoteCacheWarningsBehavior,
            default=DEFAULT_EXECUTION_OPTIONS.remote_cache_warnings,
            advanced=True,
            help=(
                "Whether to log remote cache failures at the `warn` log level.\n\n"
                "All errors not logged at the `warn` level will instead be logged at the "
                "`debug` level."
            ),
        )
        register(
            "--remote-cache-eager-fetch",
            type=bool,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_cache_eager_fetch,
            help=(
                "Eagerly fetch relevant content from the remote store instead of lazily fetching."
                "\n\nThis may result in worse performance, but reduce the frequency of errors "
                "encountered by reducing the surface area of when remote caching is used."
            ),
        )

        register(
            "--remote-execution-address",
            advanced=True,
            type=str,
            default=DEFAULT_EXECUTION_OPTIONS.remote_execution_address,
            help=(
                "The URI of a server used as a remote execution scheduler.\n\nFormat: "
                "`scheme://host:port`. The supported schemes are `grpc` and `grpcs`, i.e. gRPC "
                "with TLS enabled. If `grpc` is used, TLS will be disabled.\n\nYou must also set "
                "`--remote-store-address`, which will often be the same value."
            ),
        )
        register(
            "--remote-execution-extra-platform-properties",
            advanced=True,
            help="Platform properties to set on remote execution requests. "
            "Format: property=value. Multiple values should be specified as multiple "
            "occurrences of this flag. Pants itself may add additional platform properties.",
            type=list,
            default=DEFAULT_EXECUTION_OPTIONS.remote_execution_extra_platform_properties,
        )
        register(
            "--remote-execution-headers",
            advanced=True,
            type=dict,
            default=DEFAULT_EXECUTION_OPTIONS.remote_execution_headers,
            help=(
                "Headers to set on remote execution requests. Format: header=value. Pants "
                "may add additional headers.\n\nSee `--remote-store-headers` as well."
            ),
        )
        register(
            "--remote-execution-overall-deadline-secs",
            type=int,
            default=DEFAULT_EXECUTION_OPTIONS.remote_execution_overall_deadline_secs,
            advanced=True,
            help="Overall timeout in seconds for each remote execution request from time of submission",
        )

    @classmethod
    def register_options(cls, register):
        """Register options not tied to any particular task or subsystem."""
        # The bootstrap options need to be registered on the post-bootstrap Options instance, so it
        # won't choke on them on the command line, and also so we can access their values as regular
        # global-scope options, for convenience.
        cls.register_bootstrap_options(register)

        register(
            "--dynamic-ui",
            type=bool,
            default=(("CI" not in os.environ) and sys.stderr.isatty()),
            help="Display a dynamically-updating console UI as Pants runs. This is true by default "
            "if Pants detects a TTY and there is no 'CI' environment variable indicating that "
            "Pants is running in a continuous integration environment.",
        )

        register(
            "--tag",
            type=list,
            metavar="[+-]tag1,tag2,...",
            help=(
                "Include only targets with these tags (optional '+' prefix) or without these "
                f"tags ('-' prefix). See {bracketed_docs_url('advanced-target-selection')}."
            ),
        )
        register(
            "--exclude-target-regexp",
            type=list,
            default=[],
            metavar="<regexp>",
            help="Exclude targets that match these regexes. This does not impact file arguments.",
        )

        register(
            "--files-not-found-behavior",
            advanced=True,
            type=FilesNotFoundBehavior,
            default=FilesNotFoundBehavior.warn,
            help="What to do when files and globs specified in BUILD files, such as in the "
            "`sources` field, cannot be found. This happens when the files do not exist on "
            "your machine or when they are ignored by the `--pants-ignore` option.",
        )
        register(
            "--owners-not-found-behavior",
            advanced=True,
            type=OwnersNotFoundBehavior,
            default=OwnersNotFoundBehavior.error,
            help=(
                "What to do when file arguments do not have any owning target. This happens when "
                "there are no targets whose `sources` fields include the file argument."
            ),
        )

        register(
            "--build-patterns",
            advanced=True,
            type=list,
            default=["BUILD", "BUILD.*"],
            help=(
                "The naming scheme for BUILD files, i.e. where you define targets. This only sets "
                "the naming scheme, not the directory paths to look for. To add ignore"
                "patterns, use the option `--build-ignore`."
            ),
        )
        register(
            "--build-ignore",
            advanced=True,
            type=list,
            default=[],
            help=(
                "Paths to ignore when identifying BUILD files. This does not affect any other "
                "filesystem operations; use `--pants-ignore` for that instead. Patterns use the "
                "gitignore pattern syntax (https://git-scm.com/docs/gitignore)."
            ),
        )
        register(
            "--build-file-prelude-globs",
            advanced=True,
            type=list,
            default=[],
            help=(
                "Python files to evaluate and whose symbols should be exposed to all BUILD files. "
                f"See {bracketed_docs_url('macros')}."
            ),
        )
        register(
            "--subproject-roots",
            type=list,
            advanced=True,
            default=[],
            help="Paths that correspond with build roots for any subproject that this "
            "project depends on.",
        )

        loop_flag = "--loop"
        register(
            loop_flag,
            type=bool,
            help="Run goals continuously as file changes are detected. Alpha feature.",
        )
        register(
            "--loop-max",
            type=int,
            default=2 ** 32,
            advanced=True,
            help=f"The maximum number of times to loop when `{loop_flag}` is specified.",
        )

        register(
            "--streaming-workunits-report-interval",
            type=float,
            default=1,
            advanced=True,
            help="Interval in seconds between when streaming workunit event receivers will be polled.",
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
                "--rule-threads-core values less than 2 are not supported, but it was set to "
                f"{opts.rule_threads_core}."
            )

        if opts.remote_execution and (opts.remote_cache_read or opts.remote_cache_write):
            raise OptionsError(
                "`--remote-execution` cannot be set at the same time as either "
                "`--remote-cache-read` or `--remote-cache-write`.\n\nIf remote execution is "
                "enabled, it will already use remote caching."
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
    ) -> Tuple[str, ...]:
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
            glob_relpath = os.path.relpath(glob, buildroot)
            if glob_relpath == "." or glob_relpath.startswith(".."):
                logger.debug(
                    f"Changes to {glob}, outside of the buildroot, will not be invalidated."
                )
            else:
                invalidation_globs.update([glob_relpath, glob_relpath + "/**"])

        # Explicitly specified globs are already relative, and are added verbatim.
        invalidation_globs.update(
            (
                "!*.pyc",
                "!__pycache__/",
                # TODO: This is a bandaid for https://github.com/pantsbuild/pants/issues/7022:
                # macros should be adapted to allow this dependency to be automatically detected.
                "requirements.txt",
                "3rdparty/**/requirements.txt",
                *bootstrap_options.pantsd_invalidation_globs,
            )
        )

        return tuple(invalidation_globs)
