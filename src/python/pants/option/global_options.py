# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Type, cast

from pants.base.build_environment import is_in_container
from pants.base.deprecated import resolve_conflicting_options
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import FileContent
from pants.engine.internals.native_engine import PyExecutor
from pants.option.bootstrap_options import BootstrapOptions
from pants.option.option_types import (
    BoolOption,
    EnumOption,
    FloatOption,
    IntOption,
    StrListOption,
    collect_options_info,
)
from pants.option.option_value_container import OptionValueContainer
from pants.option.scope import GLOBAL_SCOPE
from pants.option.subsystem import Subsystem
from pants.util.dirutil import fast_relpath_optional
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.memo import memoized_classmethod, memoized_property
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import Simplifier, softwrap

logger = logging.getLogger(__name__)


class DynamicUIRenderer(Enum):
    """Which renderer to use for dynamic UI."""

    indicatif_spinner = "indicatif-spinner"
    experimental_prodash = "experimental-prodash"


class KeepSandboxes(Enum):
    """An enum for the global option `keep_sandboxes`.

    Prefer to use this rather than requesting `GlobalOptions` for more precise invalidation.
    """

    always = "always"
    on_failure = "on_failure"
    never = "never"


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

    tag = StrListOption(
        help=softwrap(
            f"""
            Include only targets with these tags (optional '+' prefix) or without these
            tags ('-' prefix). See {doc_url("docs/using-pants/advanced-target-selection")}.
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
            See {doc_url("docs/writing-plugins/macros")}.
            """
        ),
        advanced=True,
    )
    subproject_roots = StrListOption(
        help="Paths that correspond with build roots for any subproject that this project depends on.",
        advanced=True,
    )

    enable_target_origin_sources_blocks = BoolOption(
        default=False,
        help="Enable fine grained target analysis based on line numbers.",
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

    process_cleanup = BoolOption(
        # Should be aligned to `keep_sandboxes`'s `default`
        default=True,
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
        default=KeepSandboxes.never,
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
        global_options: OptionValueContainer,
    ) -> KeepSandboxes:
        resolved_value = resolve_conflicting_options(
            old_option="process_cleanup",
            new_option="keep_sandboxes",
            old_scope="",
            new_scope="",
            old_container=global_options,
            new_container=global_options,
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
            for flag in options_info.args:
                flags.add(flag)
                if len(flag) == 2:
                    short_flags.add(flag)
                elif options_info.kwargs.get("type") == bool:
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
