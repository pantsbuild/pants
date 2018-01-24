# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.build_graph.target_scopes import Scope
from pants.subsystem.subsystem import Subsystem


class IndexableJavaTargets(Subsystem):
  """Determines which java targets Kythe should act on."""
  options_scope = 'kythe-java-targets'

  @classmethod
  def register_options(cls, register):
    super(IndexableJavaTargets, cls).register_options(register)
    register('--exclude-scopes', type=list, member_type=str, fingerprint=True,
             help='Dependency scopes to exclude from indexing.')
    register('--recursive', type=bool, fingerprint=True,
             help='Index all dependencies. If false, process only target roots.')

  def get(self, context):
    """Return the indexable targets in the given context.

    Computes them lazily from the given context.  They are then fixed for the duration
    of the run, even if this method is called again with a different context.
    """
    if self.get_options().recursive:
      requested_targets = context.targets(exclude_scopes=Scope(self.get_options().exclude_scopes))
    else:
      requested_targets = list(context.target_roots)

    expanded_targets = list(requested_targets)
    # We want to act on targets derived from the specified, e.g., if acting on a binary
    # jar_library we actually want to act on the derived java_library wrapping the decompiled
    # sources.
    for t in requested_targets:
      expanded_targets.extend(context.build_graph.get_all_derivatives(t.address))

    return [t for t in expanded_targets if isinstance(t, JvmTarget) and t.has_sources('.java')]
