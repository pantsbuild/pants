# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from dataclasses import dataclass
from typing import Iterable, Union, cast, List

import humanize

from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.internals.options_parsing import _Options
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.dirutil import absolute_symlink, safe_delete, safe_rmtree, rm_rf
from pants.util.meta import frozen_after_init
from pants.base.build_environment import (
    get_buildroot,
    get_default_pants_config_file,
    get_pants_cachedir,
    is_in_container,
    pants_version,
)
from pants.option.global_options import (
    DEFAULT_EXECUTION_OPTIONS,
    DynamicRemoteOptions,
    ExecutionOptions,
    GlobalOptions,
    LocalStoreOptions,
)
from pants.init.logging import pants_log_path

class CleanSubsystem(GoalSubsystem):
    name = "clean"
    # @TODO: Note about how it can only clean disk based on current values
    help = "Clean pants caches and temp dirs"

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--dry-run",
            advanced=False,
            type=bool,
            default=True,
            help=(
                "Whether to just report what would be cleaned. A `False` value will actually clean"
                " the files on disk. Further control of what gets cleaned is provided through the"
                " advanced options, and should be conbined with `--no-dry-run`."
            ),
        )

        # Add "all" option

        # @TODO: Fill these out
        # @TODO: Is there a way to collect these programmatically?
        for named_path, help in (
            # Leaked when --no-process-execution-local-cleanup is used
            ("process-execution-temp-dirs", "@TODO"),
            # @TODO: Big cache
            ("lmdb-store", "@TODO"),
            # @TODO: Big cache
            ("named-caches", "@TODO"),
            # From ./pants run
            ("run-tracker", "@TODO"),
            # From ./pants repl
            ("repl-temp-dirs", "@TODO"),
            ("dist-dir", "@TODO"),
            ("bootstrap-dir", "@TODO"),
            # @TODO: pants-subprocessdir?
        ):
            register(
                f"--keep-{named_path}",
                advanced=True,
                type=bool,
                default=False,
                help=help,
            )


class Clean(Goal):
    subsystem_cls = CleanSubsystem

def _dir_info(*paths: Path):
    total_size = num_files = 0
    for path in paths:
        for dirpath, _, filenames in os.walk(path):
            total_size += sum(os.path.getsize(os.path.join(dirpath, f)) for f in filenames)
            num_files += len(filenames)
    return total_size, num_files

def _print_dry_run_info(
    console: Console,
    flag: str,
    human_path: str,
    paths: List[Path],
):
    # @TODO: handle empty (0 bytes or 0 files)?
    console.print_stdout(f"Would clean {console.green(human_path)}:")
    total_size, num_files = _dir_info(*paths)
    console.print_stdout(f"  Controlled by {console.blue(f'--[no-]{flag}')}")
    console.print_stdout(f"  {len(paths)} dirs, spanning {humanize.intword(num_files)} files totalling {humanize.naturalsize(total_size)}")

def _maybe_clean(
    console: Console,
    dry_run: bool,
    flag: str,
    path: Union[str, Path],
    glob: str = "*",
):
    path = Path(path)

    if dry_run:
        _print_dry_run_info(console, flag, path / glob, list(path.glob(glob)))
    else:
        pass  # @TODO: Cleaning!
    # (safe_delete, safe_delete) or rm_rf

@goal_rule
async def clean(
    clean_subsystem: CleanSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
    real_opts: _Options,
    dist_dir: DistDir,
    # specs: Specs,
) -> Clean:

    global_options = real_opts.options.for_global_scope()
    bootstrap_options = real_opts.options.bootstrap_option_values()
    pants_cache_dir = get_pants_cachedir()  # Needed for setup

    if not clean_subsystem.options.keep_process_execution_temp_dirs:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-process-execution-temp-dirs",
            Path(tempfile.gettempdir()),
            "pants-pe*",
        )

    if not clean_subsystem.options.keep_lmdb_store:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-lmdb-store",
            LocalStoreOptions.from_options(global_options).store_dir,
        )

    if not clean_subsystem.options.keep_run_tracker:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-run-tracker",
            Path(global_options.pants_workdir) / "run-tracker",
        )

    if not clean_subsystem.options.keep_repl_temp_dirs:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-repl-temp-dirs",
            Path(global_options.pants_workdir),
            "repl*",
        )

    if not clean_subsystem.options.keep_dist_dir:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-dist-dir",
            dist_dir.relpath,
        )

    if not clean_subsystem.options.keep_bootstrap_dir:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-bootstrap-dir",
            Path(pants_cache_dir) / "setup",
        )

    # N.B. This one is last because it can get quite large
    if not clean_subsystem.options.keep_named_caches:
        _maybe_clean(
            console,
            clean_subsystem.options.dry_run,
            "keep-named-caches",
            bootstrap_options.named_caches_dir,
        )

    console.print_stdout(f"Specify {console.blue('--no-dry-run')} to actually clean the disk")

    return Clean(exit_code=0)


def rules():
    return collect_rules()
