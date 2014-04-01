# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import Iterable

from twitter.common.lang import Compatibility

from pants.targets.pants_target import Pants


def resolve(arg, clazz=Pants):
  """Wraps strings in Pants() targets, for BUILD file convenience.

    - single string literal gets wrapped in Pants() target
    - single object is left alone
    - list of strings and other miscellaneous objects gets its strings wrapped in Pants() targets
  """
  if isinstance(arg, Compatibility.string):
    return clazz(arg)
  elif isinstance(arg, Iterable):
    # If arg is iterable, recurse on its elements.
    return [resolve(dependency, clazz=clazz) for dependency in arg]
  else:
    # NOTE(ryan): Ideally we'd check isinstance(arg, Target) here, but some things that Targets
    # depend on are not themselves subclasses of Target, notably JarDependencies.
    return arg
