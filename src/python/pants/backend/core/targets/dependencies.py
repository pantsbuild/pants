# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.build_graph.target import Target


logger = logging.getLogger(__name__)


class Dependencies(Target):
  """A set of dependencies that may be depended upon,
  as if depending upon the set of dependencies directly.

  NB: This class is commonly referred to by the alias 'target' in BUILD files.
  """


class DeprecatedDependencies(Dependencies):
  """A subclass for Dependencies that warns that the 'dependencies' alias is deprecated."""

  def __init__(self, *args, **kwargs):
    logger.warn("For {0} : The alias 'dependencies(..)' has been deprecated in favor of "
                "'target(..)'"
                .format(kwargs['address'].spec))
    super(DeprecatedDependencies, self).__init__(*args, **kwargs)
