# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pex.orderedset import OrderedSet

from pants.engine.console import Console
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.rules import console_rule
from pants.engine.selectors import Select


@console_rule('filedeps', [Select(Console), Select(TransitiveHydratedTargets)])
def file_deps(console, transitive_hydrated_targets):
  """List all source and BUILD files a target transitively depends on.

  Files are listed with relative paths and any BUILD files implied in the transitive closure of
  targets are also included.
  """

  uniq_set = OrderedSet()

  for hydrated_target in transitive_hydrated_targets.closure:
    if hydrated_target.address.rel_path:
      uniq_set.add(hydrated_target.address.rel_path)
    if hasattr(hydrated_target.adaptor, "sources"):
      uniq_set.update(f.path for f in hydrated_target.adaptor.sources.snapshot.files)

  for f_path in uniq_set:
    console.print_stdout(f_path)
