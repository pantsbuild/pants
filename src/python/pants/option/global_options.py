# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing
import os
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pants.base.build_environment import (
    get_buildroot,
    get_default_pants_config_file,
    get_pants_cachedir,
    get_pants_configdir,
    pants_version,
)
from pants.base.deprecated import resolve_conflicting_options
from pants.option.custom_types import dir_option
from pants.option.errors import OptionsError
from pants.option.scope import GLOBAL_SCOPE
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


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


@dataclass(frozen=True)
class ExecutionOptions:
    """A collection of all options related to (remote) execution of processes.

    TODO: These options should move to a Subsystem once we add support for "bootstrap" Subsystems (ie,
    allowing Subsystems to be consumed before the Scheduler has been created).
    """

    remote_execution: Any
    remote_store_server: Any
    remote_store_thread_count: Any
    remote_execution_server: Any
    remote_store_chunk_bytes: Any
    remote_store_chunk_upload_timeout_seconds: Any
    remote_store_rpc_retries: Any
    remote_store_connection_limit: Any
    process_execution_local_parallelism: Any
    process_execution_remote_parallelism: Any
    process_execution_cache_namespace: Any
    process_execution_cleanup_local_dirs: Any
    process_execution_speculation_delay: Any
    process_execution_speculation_strategy: Any
    process_execution_use_local_cache: Any
    remote_instance_name: Any
    remote_ca_certs_path: Any
    remote_oauth_bearer_token_path: Any
    remote_execution_extra_platform_properties: Any
    remote_execution_headers: Any
    remote_execution_overall_deadline_secs: int
    process_execution_local_enable_nailgun: bool
    remote_cache_read: bool
    remote_cache_write: bool
    remote_store_initial_timeout: int
    remote_store_timeout_multiplier: float
    remote_store_maximum_timeout: int

    @classmethod
    def from_bootstrap_options(cls, bootstrap_options):
        return cls(
            remote_execution=bootstrap_options.remote_execution,
            remote_store_server=bootstrap_options.remote_store_server,
            remote_execution_server=bootstrap_options.remote_execution_server,
            remote_store_thread_count=bootstrap_options.remote_store_thread_count,
            remote_store_chunk_bytes=bootstrap_options.remote_store_chunk_bytes,
            remote_store_chunk_upload_timeout_seconds=bootstrap_options.remote_store_chunk_upload_timeout_seconds,
            remote_store_rpc_retries=bootstrap_options.remote_store_rpc_retries,
            remote_store_connection_limit=bootstrap_options.remote_store_connection_limit,
            process_execution_local_parallelism=bootstrap_options.process_execution_local_parallelism,
            process_execution_remote_parallelism=bootstrap_options.process_execution_remote_parallelism,
            process_execution_cleanup_local_dirs=bootstrap_options.process_execution_cleanup_local_dirs,
            process_execution_speculation_delay=bootstrap_options.process_execution_speculation_delay,
            process_execution_speculation_strategy=bootstrap_options.process_execution_speculation_strategy,
            process_execution_use_local_cache=bootstrap_options.process_execution_use_local_cache,
            process_execution_cache_namespace=resolve_conflicting_options(
                old_option="remote_execution_process_cache_namespace",
                new_option="process_execution_cache_namespace",
                old_scope=GLOBAL_SCOPE,
                new_scope=GLOBAL_SCOPE,
                old_container=bootstrap_options,
                new_container=bootstrap_options,
            ),
            remote_instance_name=bootstrap_options.remote_instance_name,
            remote_ca_certs_path=bootstrap_options.remote_ca_certs_path,
            remote_oauth_bearer_token_path=bootstrap_options.remote_oauth_bearer_token_path,
            remote_execution_extra_platform_properties=bootstrap_options.remote_execution_extra_platform_properties,
            remote_execution_headers=bootstrap_options.remote_execution_headers,
            remote_execution_overall_deadline_secs=bootstrap_options.remote_execution_overall_deadline_secs,
            process_execution_local_enable_nailgun=bootstrap_options.process_execution_local_enable_nailgun,
            remote_cache_read=bootstrap_options.remote_cache_read,
            remote_cache_write=bootstrap_options.remote_cache_write,
            remote_store_initial_timeout=bootstrap_options.remote_store_initial_timeout,
            remote_store_timeout_multiplier=bootstrap_options.remote_store_timeout_multiplier,
            remote_store_maximum_timeout=bootstrap_options.remote_store_maximum_timeout,
        )


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions(
    remote_execution=False,
    remote_store_server=[],
    remote_store_thread_count=1,
    remote_execution_server=None,
    remote_store_chunk_bytes=1024 * 1024,
    remote_store_chunk_upload_timeout_seconds=60,
    remote_store_rpc_retries=2,
    remote_store_connection_limit=5,
    process_execution_local_parallelism=multiprocessing.cpu_count(),
    process_execution_remote_parallelism=128,
    process_execution_cache_namespace=None,
    process_execution_cleanup_local_dirs=True,
    process_execution_speculation_delay=1,
    process_execution_speculation_strategy="none",
    process_execution_use_local_cache=True,
    remote_instance_name=None,
    remote_ca_certs_path=None,
    remote_oauth_bearer_token_path=None,
    remote_execution_extra_platform_properties=[],
    remote_execution_headers={},
    remote_execution_overall_deadline_secs=60 * 60,  # one hour
    process_execution_local_enable_nailgun=False,
    remote_cache_read=False,
    remote_cache_write=False,
    remote_store_initial_timeout=10,
    remote_store_timeout_multiplier=2.0,
    remote_store_maximum_timeout=10,
)


class GlobalOptions(Subsystem):
    """Options to control the overall behavior of Pants."""

    options_scope = GLOBAL_SCOPE

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
            "--plugin-cache-dir",
            advanced=True,
            default=os.path.join(get_pants_cachedir(), "plugins"),
            help="Cache resolved plugin requirements here.",
        )

        register(
            "-l", "--level", type=LogLevel, default=LogLevel.INFO, help="Set the logging level."
        )
        register(
            "--show-log-target",
            type=bool,
            default=False,
            advanced=True,
            help="Display the target where a log message originates in that log message's output. "
            "This can be helpful when paired with --log-levels-by-target.",
        )

        register(
            "--log-levels-by-target",
            type=dict,
            default={},
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

        # TODO(#7203): make a regexp option type!
        register(
            "--ignore-pants-warnings",
            type=list,
            member_type=str,
            default=[],
            advanced=True,
            help="Regexps matching warning strings to ignore, e.g. "
            '["DEPRECATED: the option `--my-opt` will be removed"]. The regex patterns will be '
            "matched from the start of the warning string, and are case-insensitive.",
        )

        register(
            "--pants-version",
            advanced=True,
            default=pants_version(),
            daemon=True,
            help="Use this Pants version. Note that Pants only uses this to verify that you are "
            "using the requested version, as Pants cannot dynamically change the version it "
            "is using once the program is already running.\n\nIf you use the `./pants` script from "
            "https://www.pantsbuild.org/docs/installation, however, changing the value in your "
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
            "--pants-bootstrapdir",
            advanced=True,
            metavar="<dir>",
            default=get_pants_cachedir(),
            help="Unused. Will be deprecated in 2.2.0.",
        )
        register(
            "--pants-configdir",
            advanced=True,
            metavar="<dir>",
            default=get_pants_configdir(),
            help="Unused. Will be deprecated in 2.2.0.",
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
            "--pants-distdir-legacy-paths",
            type=bool,
            advanced=True,
            default=False,
            help=(
                "If true, will write paths for artifacts built with `./pants package` using only "
                "the target name, which may be ambiguous and result in overwriting unrelated "
                "artifacts. Otherwise, will use the target's address, e.g. "
                "`src.python.project/app.pex`, rather than `app.pex`. Use the field `output_path` "
                "to override these default values."
            ),
            removal_version="2.2.0.dev0",
            removal_hint=(
                "The pre-2.0 naming scheme for artifacts built with `./pants package` is being "
                "removed because it often resulted in ambiguity and overwriting other artifacts. "
                "Use the field `output_path` on each `pex_binary`, `python_awslambda`, and "
                "`archive` target where you would like to avoid the default."
            ),
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
                "The maximum memory usage of a pantsd process (in bytes). There is at most one "
                "pantsd process per workspace."
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
        # TODO(#7514): Make this default to 1.0 seconds if stdin is a tty!
        register(
            "--pantsd-pailgun-quit-timeout",
            advanced=True,
            type=float,
            default=5.0,
            help="The length of time (in seconds) to wait for further output after sending a "
            "signal to the remote pantsd process before killing it.",
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

        cache_instructions = (
            "The path may be absolute or relative. If the directory is within the build root, be "
            "sure to include it in `--pants-ignore`."
        )
        register(
            "--local-store-dir",
            advanced=True,
            help=(
                f"Directory to use for the local file store, which stores the results of "
                f"subprocesses run by Pants. {cache_instructions}"
            ),
            # This default is also hard-coded into the engine's rust code in
            # fs::Store::default_path so that tools using a Store outside of pants
            # are likely to be able to use the same storage location.
            default=os.path.join(get_pants_cachedir(), "lmdb_store"),
        )
        register(
            "--named-caches-dir",
            advanced=True,
            help=(
                "Directory to use for named global caches for tools and processes with trusted, "
                f"concurrency-safe caches. {cache_instructions}"
            ),
            default=os.path.join(get_pants_cachedir(), "named_caches"),
        )

        register(
            "--local-execution-root-dir",
            advanced=True,
            help=f"Directory to use for local process execution sandboxing. {cache_instructions}",
            default=tempfile.gettempdir(),
        )
        register(
            "--process-execution-use-local-cache",
            type=bool,
            default=True,
            advanced=True,
            help="Whether to keep process executions in a local cache persisted to disk.",
        )
        register(
            "--process-execution-cleanup-local-dirs",
            type=bool,
            default=True,
            advanced=True,
            help="Whether or not to cleanup directories used for local process execution "
            "(primarily useful for e.g. debugging).",
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
            "--process-execution-local-parallelism",
            type=int,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_parallelism,
            advanced=True,
            help="Number of concurrent processes that may be executed locally.",
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
            default="",
            help=(
                "The cache namespace for process execution. "
                "Change this value to invalidate every artifact's execution, or to prevent "
                "process cache entries from being (re)used for different usecases or users."
            ),
        )
        register(
            "--process-execution-speculation-delay",
            type=float,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_speculation_delay,
            advanced=True,
            help="Number of seconds to wait before speculating a second request for a slow process. "
            " see `--process-execution-speculation-strategy`",
        )
        register(
            "--process-execution-speculation-strategy",
            choices=["remote_first", "local_first", "none"],
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_speculation_strategy,
            help="Speculate a second request for an underlying process if the first one does not complete within "
            "`--process-execution-speculation-delay` seconds.\n"
            "`local_first` (default): Try to run the process locally first, "
            "and fall back to remote execution if available.\n"
            "`remote_first`: Run the process on the remote execution backend if available, "
            "and fall back to the local host if remote calls take longer than the speculation timeout.\n"
            "`none`: Do not speculate about long running processes.",
            advanced=True,
        )
        register(
            "--process-execution-local-enable-nailgun",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.process_execution_local_enable_nailgun,
            help="Whether or not to use nailgun to run the requests that are marked as nailgunnable.",
            advanced=True,
        )

        register(
            "--remote-execution",
            advanced=True,
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.remote_execution,
            help="Enables remote workers for increased parallelism. (Alpha)",
        )
        register(
            "--remote-cache-read",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.remote_cache_read,
            advanced=True,
            help="Whether to enable reading from a remote cache",
        )
        register(
            "--remote-cache-write",
            type=bool,
            default=DEFAULT_EXECUTION_OPTIONS.remote_cache_write,
            advanced=True,
            help="Whether to enable writing results to a remote cache",
        )

        register(
            "--remote-store-server",
            advanced=True,
            type=list,
            default=[],
            help="host:port of grpc server to use as remote execution file store.",
        )
        # TODO: Infer this from remote-store-connection-limit.
        register(
            "--remote-store-thread-count",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_thread_count,
            help="Thread count to use for the pool that interacts with the remote file store.",
        )
        register(
            "--remote-execution-server",
            advanced=True,
            help="host:port of grpc server to use as remote execution scheduler.",
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
            "--remote-store-connection-limit",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_connection_limit,
            help="Number of remote stores to concurrently allow connections to.",
        )
        register(
            "--remote-store-initial-timeout",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_initial_timeout,
            help="Initial timeout (in milliseconds) when there is a failure in accessing a remote store.",
        )
        register(
            "--remote-store-timeout-multiplier",
            type=float,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_timeout_multiplier,
            help="Multiplier used to increase the timeout (starting with value of --remote-store-initial-timeout) between retry attempts in accessing a remote store.",
        )
        register(
            "--remote-store-maximum-timeout",
            type=int,
            advanced=True,
            default=DEFAULT_EXECUTION_OPTIONS.remote_store_maximum_timeout,
            help="Maximum timeout (in millseconds) to allow between retry attempts in accessing a remote store.",
        )
        register(
            "--remote-execution-process-cache-namespace",
            advanced=True,
            removal_version="2.2.0.dev0",
            removal_hint="Use the `--process-execution-cache-namespace` option instead.",
            help="The cache namespace for remote process execution. "
            "Bump this to invalidate every artifact's remote execution. "
            "This is the remote execution equivalent of the legacy cache-key-gen-version "
            "flag.",
        )
        register(
            "--remote-instance-name",
            advanced=True,
            help="Name of the remote execution instance to use. Used for routing within "
            "--remote-execution-server and --remote-store-server.",
        )
        register(
            "--remote-ca-certs-path",
            advanced=True,
            help="Path to a PEM file containing CA certificates used for verifying secure "
            "connections to --remote-execution-server and --remote-store-server. "
            "If not specified, TLS will not be used.",
        )
        register(
            "--remote-oauth-bearer-token-path",
            advanced=True,
            help="Path to a file containing an oauth token to use for grpc connections to "
            "--remote-execution-server and --remote-store-server. If not specified, no "
            "authorization will be performed.",
        )
        register(
            "--remote-execution-extra-platform-properties",
            advanced=True,
            help="Platform properties to set on remote execution requests. "
            "Format: property=value. Multiple values should be specified as multiple "
            "occurrences of this flag. Pants itself may add additional platform properties.",
            type=list,
            default=[],
        )
        register(
            "--remote-execution-headers",
            advanced=True,
            help="Headers to set on remote execution requests. "
            "Format: header=value. Pants itself may add additional headers.",
            type=dict,
            default={},
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
                "tags ('-' prefix). See https://www.pantsbuild.org/docs/advanced-target-selection."
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
                "See https://www.pantsbuild.org/docs/macros."
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
            default=10,
            advanced=True,
            help="Interval in seconds between when streaming workunit event receivers will be polled.",
        )
        register(
            "--streaming-workunits-handlers",
            type=list,
            member_type=str,
            default=[],
            advanced=True,
            help="Use this option to name Subsystems which will receive streaming workunit events. "
            "For instance, `--streaming-workunits-handlers=\"['pants.reporting.workunit.Workunits']\"` will "
            'register a Subsystem called Workunits defined in the module "pants.reporting.workunit".',
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
        if opts.remote_execution and not opts.remote_execution_server:
            raise OptionsError(
                "The `--remote-execution` option requires also setting "
                "`--remote-execution-server` to work properly."
            )

        if opts.remote_execution_server and not opts.remote_store_server:
            raise OptionsError(
                "The `--remote-execution-server` option requires also setting "
                "`--remote-store-server`. Often these have the same value."
            )
        if opts.remote_cache_read and not opts.remote_store_server:
            raise OptionsError(
                "The `--remote-cache-read` option requires also setting "
                "`--remote-store-server` to work properly."
            )
        if opts.remote_cache_write and not opts.remote_store_server:
            raise OptionsError(
                "The `--remote-cache-write` option requires also setting "
                "`--remote-store-server` to work properly."
            )

        # Ensure that timeout values are non-zero.
        if opts.remote_store_initial_timeout <= 0:
            raise OptionsError(
                "The --remote-store-initial-timeout option requires a positive number of milliseconds."
            )
        if opts.remote_store_timeout_multiplier <= 0.0:
            raise OptionsError(
                "The --remote-store-timeout-multiplier option requires a positive number for the multiplier."
            )
        if opts.remote_store_maximum_timeout <= 0:
            raise OptionsError(
                "The --remote-store-initial-timeout option requires a positive number of milliseconds."
            )
