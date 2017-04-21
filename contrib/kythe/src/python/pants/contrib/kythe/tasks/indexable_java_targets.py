# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.build_graph.target_scopes import Scopes


class IndexableJavaTargets(object):
  """Determines which java targets Kythe should act on."""

  @classmethod
  def get(cls, context):
    """Return the indexable targets in the given context.

    Computes them lazily from the given context.  They are then fixed for the duration
    of the run, even if this method is called again with a different context.
    """
    if not cls._targets:
      # TODO: Should we index COMPILE scoped deps? E.g., annotations?
      cls._targets = context.targets(
        lambda t: isinstance(t, JvmTarget) and t.has_sources('.java'),
        exclude_scopes=Scopes.COMPILE
      )
    return cls._targets

  _targets = None
