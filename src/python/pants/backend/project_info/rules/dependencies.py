# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get


# TODO(#8762) Get this rule to feature parity with the dependencies task.
class DependenciesOptions(LineOriented, GoalSubsystem):
  name = 'dependencies2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--transitive',
      default=True,
      type=bool,
      help='Run dependencies against transitive dependencies of targets specified on the command line.',
    )


class Dependencies(Goal):
  subsystem_cls = DependenciesOptions

@goal_rule
async def dependencies(
  console: Console, build_file_addresses: BuildFileAddresses, options: DependenciesOptions,
) -> Dependencies:
  addresses: Set[str] = set()
  if options.values.transitive:
    transitive_targets = await Get[TransitiveHydratedTargets](
      BuildFileAddresses, build_file_addresses,
    )
    transitive_dependencies = transitive_targets.closure - set(transitive_targets.roots)
    addresses.update(hydrated_target.address.spec for hydrated_target in transitive_dependencies)
  else:
    hydrated_targets = await Get[HydratedTargets](BuildFileAddresses, build_file_addresses)
    addresses.update(
      dep.spec
      for hydrated_target in hydrated_targets
      for dep in hydrated_target.dependencies
    )

  with options.line_oriented(console) as print_stdout:
    for address in sorted(addresses):
      print_stdout(address)

  return Dependencies(exit_code=0)


def rules():
  return [
    dependencies,
  ]
