# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.java.distribution.distribution import Distribution, DistributionLocator


@dataclass(frozen=True)
class JvmDistributionSearchSettings:
  args: Tuple[str, ...] = ()


@rule
def non_strict_select_jvm_distribution(
    settings: JvmDistributionSearchSettings,
) -> Distribution:
  """General utility method to select a jvm distribution, falling back to non-strict selection."""
  try:
    local_distribution = JvmPlatform.preferred_jvm_distribution(settings.args, strict=True)
  except DistributionLocator.Error:
    local_distribution = JvmPlatform.preferred_jvm_distribution(settings.args, strict=False)
  return local_distribution


@dataclass(frozen=True)
class HermeticDist:
  home: str
  underlying: Distribution

  @property
  def symbolic_home(self) -> str:
    return self.home

  @property
  def underlying_home(self) -> str:
    return self.underlying.home


@rule
async def hermetic_dist() -> HermeticDist:
  local_dist = await Get[Distribution](JvmDistributionSearchSettings())
  return HermeticDist('.jdk', local_dist)


def rules():
  return [
    non_strict_select_jvm_distribution,
    hermetic_dist,
  ]
