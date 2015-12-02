# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated
from pants.build_graph.target import Target


class Dependencies(Target):
  """A set of dependencies that may be depended upon,
  as if depending upon the set of dependencies directly.

  NB: This class is commonly referred to by the alias 'target' in BUILD files.
  """

  @deprecated('0.0.64', 'Replace dependencies(...) with target(...) in your BUILD files. '
                        'Replace uses of Dependencies with Target in your code.')
  def __init__(self, *args, **kwargs):
    raise RuntimeError('For {}: dependencies(...) targets no longer work. Replace with '
                       'target(...) in your BUILD files.'.format(kwargs['address'].spec))
