# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.specs import Specs
from pants.core.goals.fmt import FmtSubsystemBase, _fmt_impl
from pants.core.goals.style_request import only_option_help as make_only_option_help
from pants.core.goals.style_request import style_batch_size_help
from pants.engine.console import Console
from pants.engine.fs import Workspace
from pants.engine.goal import Goal
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.unions import UnionMembership


class FixSubsystem(FmtSubsystemBase):
    name = "fix"
    help = "Autofix source code."
    only_option_help = make_only_option_help("fix", "fixer", "autoflake", "pyupgrade")
    batch_size_option_help = style_batch_size_help(uppercase="Fixer", lowercase="fixer")


class Fix(Goal):
    subsystem_cls = FixSubsystem


# This is it! We're just going to completely piggy-back off `fmt` for `fix`. Plugins just need to
# register a union implementation which subclasses `FmtTargetsRequest` and sets the class variable
# `goal_name` to `"fix"`.


@goal_rule
async def fmt(
    console: Console,
    specs: Specs,
    fix_subsystem: FixSubsystem,
    build_file_options: BuildFileOptions,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fix:
    result = await _fmt_impl(
        console=console,
        specs=specs,
        subsystem=fix_subsystem,
        build_file_options=build_file_options,
        workspace=workspace,
        union_membership=union_membership,
    )
    return Fix(result.exit_code)


def rules():
    return collect_rules()
