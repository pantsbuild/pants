# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.base.specs import Specs
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.rules import console_rule
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

@console_rule
async def dependencies(
  console: Console, specs: Specs, options: DependenciesOptions
) -> Dependencies:
  addresses: Set[str] = set()
  if options.values.transitive:
    transitive_targets = await Get[TransitiveHydratedTargets](Specs, specs)
    addresses.update(hydrated_target.address.spec for hydrated_target in transitive_targets.closure)
    # transitive_targets.closure includes the initial target. To keep the behavior consistent with intransitive
    # dependencies, we remove the initial target from the set of addresses.
    for single_address in specs.dependencies:
      addresses.discard(single_address.to_spec_string())
  else:
    hydrated_targets = await Get[HydratedTargets](Specs, specs)
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
