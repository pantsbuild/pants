# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import Iterable, cast

from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.internals.options_parsing import _Options
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.dirutil import absolute_symlink
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

class CleanSubsystem(GoalSubsystem):
    name = "clean"
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

        # @TODO:
        register(
            "--process-execution-temp-dirs",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "@TODO"
            ),
        )

        register(
            "--lmdb-store",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "@TODO"
            ),
        )

        register(
            "--named-caches",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "@TODO"
            ),
        )

    @property
    def clean_process_execution_temp_dirs(self) -> bool:
        if self.options.dry_run:
            pass
        return self.options.process_execution_temp_dirs

class Clean(Goal):
    subsystem_cls = CleanSubsystem


@goal_rule
async def clean(
    clean_subsystem: CleanSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
    real_opts: _Options,
    # specs: Specs,
) -> Clean:

    print(tempfile.gettempdir())

    if clean_subsystem.options.lmdb_store:
        local_store_options = LocalStoreOptions.from_options(real_opts.options.for_global_scope())
        if clean_subsystem.options.dry_run:
            console.print_stdout(f"Would clean '{local_store_options.store_dir}'")
        else:
            ...  # @TODO: Clean!

    if clean_subsystem.options.named_caches:
        bootstrap_option_values = real_opts.options.bootstrap_option_values()
        if clean_subsystem.options.dry_run:
            console.print_stdout(f"Would clean '{bootstrap_option_values.named_caches_dir}'")
        else:
            ...  # @TODO: Clean!

    console.print_stdout(clean_subsystem.options.is_default("dry_run"))
    return Clean(exit_code=0)


def rules():
    return collect_rules()
