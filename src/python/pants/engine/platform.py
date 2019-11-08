# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable, List

from pants.engine.rules import rule
from pants.util.collections import Enum
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.osutil import get_normalized_os_name


class Platform(Enum):
  darwin = "darwin"
  linux = "linux"

  # TODO: try to turn all of these accesses into v2 dependency injections!
  @memoized_classproperty
  def current(cls) -> 'Platform':
    return Platform(get_normalized_os_name())

  @memoized_property
  def runtime_lib_path_env_var(self) -> str:
    return self.match({
      Platform.darwin: "DYLD_LIBRARY_PATH",
      Platform.linux: "LD_LIBRARY_PATH",
    })


class PlatformConstraint(Enum):
  darwin = "darwin"
  linux = "linux"
  none = "none"

  @memoized_classproperty
  def local_platform(cls) -> 'PlatformConstraint':
    return PlatformConstraint(Platform.current.value)


# TODO We will want to allow users to specify the execution platform for rules,
# which means replacing this singleton rule with a RootRule populated by an option.
@rule
def materialize_platform() -> Platform:
  current: Platform = Platform.current
  return current


def create_platform_rules() -> List[Callable]:
  return [materialize_platform]
