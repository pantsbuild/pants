# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import rule
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.objects import enum
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name


class Platform(enum(all_normalized_os_names())):

  # TODO: try to turn all of these accesses into v2 dependency injections!
  @memoized_classproperty
  def current(cls):
    return cls(get_normalized_os_name())

  @memoized_property
  def runtime_lib_path_env_var(self):
    return self.resolve_for_enum_variant({
      'darwin': 'DYLD_LIBRARY_PATH',
      'linux': 'LD_LIBRARY_PATH',
    })


class PlatformConstraint(enum(list(all_normalized_os_names()) + ['none'])):
  @memoized_classproperty
  def local_platform(cls):
    return cls(Platform.current.value)


# TODO We will want to allow users to specify the execution platform for rules,
# which means replacing this singleton rule with a RootRule populated by an option.
@rule(Platform, [])
def materialize_platform():
  return Platform.current


def create_platform_rules():
  return [materialize_platform]
