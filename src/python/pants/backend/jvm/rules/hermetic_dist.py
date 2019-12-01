# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.engine.rules import rule


@dataclass(frozen=True)
class HermeticDist:
  underlying: JvmCompile._HermeticDistribution

  @property
  def underlying_home(self) -> str:
    return self.underlying.underlying_home


@rule
def hermetic_dist() -> HermeticDist:
  local_dist = JvmCompile._local_jvm_distribution()
  hermetic_dist = JvmCompile._HermeticDistribution('.jdk', local_dist)
  return HermeticDist(hermetic_dist)


def rules():
  return [
    hermetic_dist,
  ]
