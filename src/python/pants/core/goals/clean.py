# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union

import humanize

from pants.base.build_environment import get_pants_cachedir
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.options_parsing import _Options
from pants.engine.rules import collect_rules, goal_rule
from pants.option.global_options import LocalStoreOptions
from pants.util.dirutil import rm_rf

# N.B. We use a list so that named-caches can go last, as it is quite large and for dry-run
# it's a nicer UX if it's last.
_NAMED_CACHE_FLAGS_INFO = [
    (
        "process-execution-temp-dirs",
        "Whether to keep the process execution temporary directories. These are normally cleaned up"
        " automatically, however they are leaked if --no-process-execution-local-cleanup.",
    ),
    (
        "lmdb-store",
        "Whether to keep the local file store, which stores the results of subprocesses run by Pants.",
    ),
    (
        "run-tracker",
        "Whether to clean directories persisted after using `./pants run`.",
    ),
    (
        "repl-temp-dirs",
        "Whether to clean directories persisted after using `./pants repl`.",
    ),
    ("dist-dir", "Whether to clean the distributable files directory. "),
    ("bootstrap-dir", "Whether to clean directories used by pants for bootstrapping itself."),
    ("named-caches", "Whether to clean the named global caches."),
]


def _dir_info(*paths: Path):
    total_size = num_files = 0
    for path in paths:
        for dirpath, _, filenames in os.walk(path):
            total_size += sum(os.path.getsize(os.path.join(dirpath, f)) for f in filenames)
            num_files += len(filenames)
    return total_size, num_files


class CleanSubsystem(GoalSubsystem):
    name = "clean"
    help = "Clean pants caches and temp dirs (based on current settings)"

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--dry-run",
            advanced=False,
            type=bool,
            default=True,
            help=("Whether to just report what would be cleaned. @TODO: more"),
        )
        register(
            "--all",
            advanced=False,
            type=bool,
            default=False,  # @TODO: True?
            help=(
                "Clear all caches. Can be combined with the advanced options for further control."
            ),
        )

        # @TODO: Is there a way to collect these programmatically?
        for flag_slug, help in _NAMED_CACHE_FLAGS_INFO:
            register(
                f"--keep-{flag_slug}",
                advanced=True,
                type=bool,
                default=True,
                help=help,
            )


class Clean(Goal):
    subsystem_cls = CleanSubsystem


@goal_rule
async def clean(
    clean_subsystem: CleanSubsystem,
    console: Console,
    real_opts: _Options,
    dist_dir: DistDir,
) -> Clean:
    def _maybe_clean(
        keep_flag_slug: str,
        keep_flag_value: bool,
        path: Union[str, Path],
        glob: str = "*",
    ):
        path = Path(path)
        paths = list(path.glob(glob))
        should_clean = (clean_subsystem.options.all and not keep_flag_value) or (
            clean_subsystem.options.all and not not keep_flag_value
        )

        if clean_subsystem.options.dry_run:
            # @TODO: handle empty (0 bytes or 0 files) specially?
            total_size, num_files = _dir_info(*paths)
            maybe_negative = "" if should_clean else console.red("not ")

            console.print_stdout(f"Would {maybe_negative}clean {console.green(path / glob)}:")
            # @TODO: Print the relevant flag that gave us this directory?
            console.print_stdout(f"  Controlled by {console.blue(f'--[no-]keep-{keep_flag_slug}')}")
            console.print_stdout(
                f"  {len(paths)} dirs, spanning {humanize.intword(num_files)} files totalling {humanize.naturalsize(total_size)}"
            )
        elif should_clean:
            # @TODO: Should we multi-process this?
            console.print_stdout(f"Cleaning {console.green(path / glob)}")
            for path in paths:
                rm_rf(str(path))

    global_options = real_opts.options.for_global_scope()
    bootstrap_options = real_opts.options.bootstrap_option_values()
    pants_cache_dir = get_pants_cachedir()

    for flag_slug, _ in _NAMED_CACHE_FLAGS_INFO:
        _maybe_clean(
            flag_slug,
            getattr(clean_subsystem.options, f"keep_{flag_slug.replace('-', '_')}"),
            *{
                "process-execution-temp-dirs": (Path(tempfile.gettempdir()), "pants-pe*"),
                "lmdb-store": (LocalStoreOptions.from_options(global_options).store_dir,),
                "run-tracker": (Path(global_options.pants_workdir) / "run-tracker",),
                "repl-temp-dirs": (Path(global_options.pants_workdir), "repl*"),
                "dist-dir": (dist_dir.relpath,),
                "bootstrap-dir": (Path(pants_cache_dir) / "setup",),
                "named-caches": (bootstrap_options.named_caches_dir,),
            }[flag_slug],
        )

    if clean_subsystem.options.dry_run:
        console.print_stdout(f"Specify {console.blue('--no-dry-run')} to actually do the cleaning")

    return Clean(exit_code=0)


def rules():
    return collect_rules()
