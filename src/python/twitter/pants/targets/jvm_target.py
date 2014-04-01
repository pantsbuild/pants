# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.collections import maybe_list

from pants.targets.exclude import Exclude
from pants.targets.internal import InternalTarget
from pants.targets.jarable import Jarable
from pants.targets.with_sources import TargetWithSources


class JvmTarget(InternalTarget, TargetWithSources, Jarable):
  """A base class for all java module targets that provides path and dependency translation."""

  def __init__(self,
               name,
               sources,
               dependencies,
               excludes=None,
               configurations=None,
               exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: One or more :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param configurations: One or more ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """
    InternalTarget.__init__(self, name, dependencies, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources)

    self.add_labels('jvm')
    for source in self.sources:
      rel_path = os.path.join(self.target_base, source)
      TargetWithSources.register_source(rel_path, self)
    self.excludes = maybe_list(excludes or [], Exclude)
    self.configurations = maybe_list(configurations or [])

  def _provides(self):
    return None
