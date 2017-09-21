# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os


def is_coverage_target(tgt):
  return (tgt.is_java or tgt.is_scala) and not tgt.is_test and not tgt.is_synthetic


def initialize_instrument_classpath(settings, targets, instrumentation_classpath):
  """Clones the existing runtime_classpath and corresponding binaries to instrumentation specific
  paths.

  :param targets: the targets for which we should create an instrumentation_classpath entry based
  on their runtime_classpath entry.
  """
  settings.safe_makedir(settings.coverage_instrument_dir, clean=True)

  for target in targets:
    if not is_coverage_target(target):
      continue
    # Do not instrument transitive dependencies.
    paths = instrumentation_classpath.get_for_target(target)
    target_instrumentation_path = os.path.join(settings.coverage_instrument_dir, target.id)
    for (index, (config, path)) in enumerate(paths):
      # There are two sorts of classpath entries we see in the compile classpath: jars and dirs.
      # The branches below handle the cloning of those respectively.
      entry_instrumentation_path = os.path.join(target_instrumentation_path, str(index))
      if settings.is_file(path):
        settings.safe_makedir(entry_instrumentation_path, clean=True)
        settings.copy2(path, entry_instrumentation_path)
        new_path = os.path.join(entry_instrumentation_path, os.path.basename(path))
      else:
        settings.copytree(path, entry_instrumentation_path)
        new_path = entry_instrumentation_path

      instrumentation_classpath.remove_for_target(target, [(config, path)])
      instrumentation_classpath.add_for_target(target, [(config, new_path)])
      settings.log.debug(
        "runtime_classpath ({}) cloned to instrument_classpath ({})".format(path, new_path))
