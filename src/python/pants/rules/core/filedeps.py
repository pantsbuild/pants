# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.orderedset import OrderedSet

from pants.engine.console import Console
from pants.engine.goal import Goal, LineOriented
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.rules import console_rule


class Filedeps(LineOriented, Goal):
  """List all source and BUILD files a target transitively depends on.

  Files may be listed with absolute or relative paths and any BUILD files implied in the transitive
  closure of targets are also included.
  """

  # TODO: Until this implements more of the options of `filedeps`, it can't claim the name!
  name = 'fast-filedeps'


@console_rule(Filedeps, [Console, Filedeps.Options, TransitiveHydratedTargets])
def file_deps(console, filedeps_options, transitive_hydrated_targets):

  uniq_set = OrderedSet()

  for hydrated_target in transitive_hydrated_targets.closure:
    if hydrated_target.address.rel_path:
      uniq_set.add(hydrated_target.address.rel_path)
    if hasattr(hydrated_target.adaptor, "sources"):
      uniq_set.update(hydrated_target.adaptor.sources.snapshot.files)

  with Filedeps.line_oriented(filedeps_options, console) as (print_stdout, print_stderr):
    for f_path in uniq_set:
      print_stdout(f_path)

  return Filedeps(exit_code=0)


def rules():
  return [
      file_deps,
    ]
