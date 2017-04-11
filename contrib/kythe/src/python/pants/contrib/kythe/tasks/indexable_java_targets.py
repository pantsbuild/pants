# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.build_graph.target_scopes import Scopes
from pants.util.memo import memoized_method


class IndexableJavaTargets(object):
  """Determines which java targets Kythe should act on."""

  @classmethod
  @memoized_method
  def get(cls, context):
    """Return the indexable targets in the given context."""
    # TODO: Should we index COMPILE scoped deps? E.g., annotations?
    return context.targets(
      lambda t: isinstance(t, JvmTarget) and t.has_sources('.java'),
      exclude_scopes=Scopes.COMPILE
    )
