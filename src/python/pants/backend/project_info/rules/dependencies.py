# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import Set

from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets, TransitiveHydratedTargets
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.legacy.structs import PythonRequirementLibraryAdaptor


class DependencyType(Enum):
    SOURCE = "source"
    THIRD_PARTY = "3rdparty"
    SOURCE_AND_THIRD_PARTY = "source-and-3rdparty"


# TODO(#8762) Get this rule to feature parity with the dependencies task.
class DependenciesOptions(LineOriented, GoalSubsystem):
    """Print the target's dependencies."""

    name = "dependencies2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--transitive",
            default=False,
            type=bool,
            help="Run dependencies against transitive dependencies of targets specified on the command line.",
        )
        # TODO(#8762): Wire this up. Currently we only support `internal`.
        register(
            "--type",
            type=DependencyType,
            default=DependencyType.SOURCE,
            help="Which types of dependencies to find, where `source` means source code dependencies "
            "and `3rdparty` means third-party requirements and JARs.",
        )


class Dependencies(Goal):
    subsystem_cls = DependenciesOptions


@goal_rule
async def dependencies(
<<<<<<< HEAD
    console: Console, addresses: Addresses, options: DependenciesOptions,
) -> Dependencies:
    address_strings: Set[str] = set()
    if options.values.transitive:
        transitive_targets = await Get[TransitiveHydratedTargets](Addresses, addresses)
        transitive_dependencies = transitive_targets.closure - set(transitive_targets.roots)
        address_strings.update(
            hydrated_target.adaptor.address.spec for hydrated_target in transitive_dependencies
        )
    else:
        hydrated_targets = await Get[HydratedTargets](Addresses, addresses)
        address_strings.update(
            dep.spec
            for hydrated_target in hydrated_targets
            for dep in hydrated_target.adaptor.dependencies
        )

    with options.line_oriented(console) as print_stdout:
        for address in sorted(address_strings):
            print_stdout(address)

    return Dependencies(exit_code=0)
=======
  console: Console,
  build_file_addresses: BuildFileAddresses,
  options: DependenciesOptions,
) -> Dependencies:
  addresses: Set[str] = set()
  third_party_targets: Set[HydratedTarget] = set()
  if options.values.transitive:
    transitive_targets = await Get[TransitiveHydratedTargets](
      BuildFileAddresses, build_file_addresses,
    )
    transitive_dependencies = transitive_targets.closure - set(transitive_targets.roots)
    for hydrated_target in transitive_dependencies:
      address = hydrated_target.address.spec
      if address.startswith('3rdparty'):
        third_party_targets.add(hydrated_target)
      else:
        addresses.add(address)
    # targets.update(transitive_dependencies)
    # addresses.update(hydrated_target.address.spec for hydrated_target in transitive_dependencies)
  else:
    hydrated_targets = await Get[HydratedTargets](BuildFileAddresses, build_file_addresses)
    addresses.update(
      dep.spec
      for hydrated_target in hydrated_targets
      for dep in hydrated_target.dependencies
    )

  if options.values.type in [DependencyType.SOURCE, DependencyType.SOURCE_AND_THIRD_PARTY]:
    with options.line_oriented(console) as print_stdout:
      for address in sorted(addresses):
        print_stdout(address)
  if options.values.type in [DependencyType.THIRD_PARTY, DependencyType.SOURCE_AND_THIRD_PARTY]:
    # TODO(John Sirois): We need an external payload abstraction at which point knowledge
    # of jar and requirement payloads can go and this hairball will be untangled.

    for hydrated_target in third_party_targets:
      if isinstance(hydrated_target.adaptor, PythonRequirementLibraryAdaptor):
        for requirement in hydrated_target.adaptor.requirements:
          with options.line_oriented(console) as print_stdout:
            print_stdout(requirement.requirement)
    import pdb; pdb.set_trace()
    # if isinstance(tgt.payload.get_field('requirements'), PythonRequirementsField):
    #   for requirement in tgt.payload.requirements:
    #     yield str(requirement.requirement)
    # elif isinstance(tgt.payload.get_field('jars'), JarsField):
    #   for jar in tgt.payload.jars:
    #     data = dict(org=jar.org, name=jar.name, rev=jar.rev)
    #     yield (f'{jar.org}:{jar.name}:{jar.rev}' if jar.rev else f'{jar.org}:{jar.name}')


  return Dependencies(exit_code=0)
>>>>>>> begin external deps


def rules():
    return [
        dependencies,
    ]
