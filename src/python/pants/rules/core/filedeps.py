# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import Set

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get


class FiledepsOptions(LineOriented, GoalSubsystem):
  """List all source and BUILD files a target transitively depends on.

  Files may be listed with absolute or relative paths and any BUILD files implied in the transitive
  closure of targets are also included.
  """
  name = 'filedeps2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--absolute', type=bool, default=True,
      help='If True, output with absolute path; else, output with path relative to the build root'
    )
    register(
      '--globs', type=bool,
      help='Instead of outputting filenames, output globs (ignoring excludes)'
    )


class Filedeps(Goal):
  subsystem_cls = FiledepsOptions


@goal_rule
async def file_deps(
  console: Console,
  options: FiledepsOptions,
  build_root: BuildRoot,
  transitive_hydrated_targets: TransitiveHydratedTargets,
) -> Filedeps:
  unique_rel_paths: Set[str] = set()
  for hydrated_target in transitive_hydrated_targets.closure:
    adaptor = hydrated_target.adaptor

    bfa = await Get[BuildFileAddress](Address, hydrated_target.address)
    unique_rel_paths.add(bfa.rel_path)

    if hasattr(adaptor, "sources"):
      sources_paths = (
        adaptor.sources.snapshot.files
        if not options.values.globs
        else adaptor.sources.filespec["globs"]
      )
      unique_rel_paths.update(sources_paths)

  with options.line_oriented(console) as print_stdout:
    for rel_path in sorted(unique_rel_paths):
      final_path = str(Path(build_root.path, rel_path)) if options.values.absolute else rel_path
      print_stdout(final_path)

  return Filedeps(exit_code=0)


def rules():
  return [
      file_deps,
    ]
