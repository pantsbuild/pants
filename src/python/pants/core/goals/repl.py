# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Dict, Tuple, Type, cast

from pants.base.build_root import BuildRoot
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_process import InteractiveProcess, InteractiveRunner
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import Field, Target, Targets, TransitiveTargets
from pants.engine.unions import UnionMembership, union
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir


@union
@dataclass(frozen=True)
class ReplImplementation(ABC):
    """This type proxies from the top-level `repl` goal to a specific REPL implementation for a
    specific language or languages."""

    name: ClassVar[str]
    required_fields: ClassVar[Tuple[Type[Field], ...]]

    targets: Targets

    @classmethod
    def is_valid(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)


class ReplOptions(GoalSubsystem):
    """Opens a REPL."""

    name = "repl"
    required_union_implementations = (ReplImplementation,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--shell",
            type=str,
            default=None,
            fingerprint=True,
            help="Override the automatically-detected REPL program for the target(s) specified. ",
        )


class Repl(Goal):
    subsystem_cls = ReplOptions


@dataclass(frozen=True)
class ReplBinary:
    digest: Digest
    binary_name: str


@goal_rule
async def run_repl(
    console: Console,
    workspace: Workspace,
    interactive_runner: InteractiveRunner,
    options: ReplOptions,
    transitive_targets: TransitiveTargets,
    build_root: BuildRoot,
    union_membership: UnionMembership,
    global_options: GlobalOptions,
) -> Repl:
    default_repl = "python"
    repl_shell_name = cast(str, options.values.shell) or default_repl

    implementations: Dict[str, Type[ReplImplementation]] = {
        impl.name: impl for impl in union_membership[ReplImplementation]
    }
    repl_implementation_cls = implementations.get(repl_shell_name)
    if repl_implementation_cls is None:
        available = sorted(implementations.keys())
        console.print_stderr(
            f"{repr(repl_shell_name)} is not a registered REPL. Available REPLs (which may "
            f"be specified through the option `--repl-shell`): {available}"
        )
        return Repl(-1)

    repl_impl = repl_implementation_cls(
        targets=Targets(
            tgt for tgt in transitive_targets.closure if repl_implementation_cls.is_valid(tgt)
        )
    )
    repl_binary = await Get[ReplBinary](ReplImplementation, repl_impl)

    with temporary_dir(root_dir=global_options.options.pants_workdir, cleanup=False) as tmpdir:
        path_relative_to_build_root = PurePath(tmpdir).relative_to(build_root.path).as_posix()
        workspace.materialize_directory(
            DirectoryToMaterialize(repl_binary.digest, path_prefix=path_relative_to_build_root)
        )

        full_path = PurePath(tmpdir, repl_binary.binary_name).as_posix()
        process = InteractiveProcess(argv=[full_path], run_in_workspace=True)

    result = interactive_runner.run_process(process)
    return Repl(result.exit_code)


def rules():
    return [run_repl]
