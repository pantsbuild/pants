# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.base.build_environment import get_buildroot
from pants.engine.console import Console
from pants.engine.goal import Goal, LineOriented
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.rules import console_rule


class Filedeps(LineOriented, Goal):
  """List all source and BUILD files a target transitively depends on.

  Files may be listed with absolute or relative paths and any BUILD files implied in the transitive
  closure of targets are also included.
  """

  # TODO: Until this implements `--globs`, this can't claim the name `filedeps`!
  name = 'fast-filedeps'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--absolute', type=bool, default=True,
      help='If True, output with absolute path; else, output with path relative to the build root.'
    )


@console_rule
def file_deps(
  console: Console,
  filedeps_options: Filedeps.Options,
  transitive_hydrated_targets: TransitiveHydratedTargets
) -> Filedeps:

  absolute = filedeps_options.values.absolute

  unique_rel_paths = set()
  build_root = get_buildroot()

  for hydrated_target in transitive_hydrated_targets.closure:
    if hydrated_target.address.rel_path:
      unique_rel_paths.add(hydrated_target.address.rel_path)
    if hasattr(hydrated_target.adaptor, "sources"):
      unique_rel_paths.update(hydrated_target.adaptor.sources.snapshot.files)

  with Filedeps.line_oriented(filedeps_options, console) as print_stdout:
    for rel_path in sorted(unique_rel_paths):
      final_path = str(Path(build_root, rel_path)) if absolute else rel_path
      print_stdout(final_path)

  return Filedeps(exit_code=0)


def rules():
  return [
      file_deps,
    ]
