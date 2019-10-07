# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import FrozenSet, List, Tuple

from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import RootRule, rule


@dataclass(frozen=True)
class BuildConstraintsForAdaptors:
  adaptors: Tuple[PythonTargetAdaptor]


@dataclass(frozen=True)
class PexInterpreterContraints:
  constraint_set: FrozenSet[str] = frozenset()

  def generate_pex_arg_list(self) -> List[str]:
    args = []
    for constraint in self.constraint_set:
      args.extend(["--interpreter-constraint", constraint])
    return args


@rule
def handle_constraints(build_constraints_for_adaptors: BuildConstraintsForAdaptors, python_setup: PythonSetup) -> PexInterpreterContraints:
  interpreter_constraints = frozenset(
    [constraint
    for target_adaptor in build_constraints_for_adaptors.adaptors
    for constraint in python_setup.compatibility_or_constraints(
      getattr(target_adaptor, 'compatibility', None)
    )]
  )

  yield PexInterpreterContraints(constraint_set=interpreter_constraints)


def rules():
  return [handle_constraints, RootRule(BuildConstraintsForAdaptors)]

