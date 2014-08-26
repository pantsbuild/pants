# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import itertools
import os

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.targets.jvm_binary import JvmApp
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.build_environment import get_buildroot


# XXX(pl): JVM hairball violator
class FileDeps(ConsoleTask):
  """List all transitive file dependencies of the targets specified on the command line.

  Files are listed with absolute paths and any BUILD files implied in the transitive closure of
  targets are also included.
  """

  def console_output(self, targets):
    # TODO(John Sirois): This hacks around ScalaLibraries' psuedo-deps on JavaLibraries.  We've
    # already tried to tuck away this hack by subclassing closure() in ScalaLibrary - but in this
    # case that's not enough when a ScalaLibrary with java_sources is an interior node of the
    # active context graph.  This awkwardness should be eliminated when ScalaLibrary can point
    # to a java source set as part of its 1st class sources.
    all_targets = set()
    for target in targets:
      all_targets.add(target)
      if isinstance(target, ScalaLibrary):
        all_targets.update(target.java_sources)

    buildroot = get_buildroot()
    files = set()
    for target in all_targets:
      files.add(target.concrete_derived_from.address.build_file.full_path)
      if target.has_sources():
        files.update(os.path.join(buildroot, src)
                     for src in target.sources_relative_to_buildroot())
      # TODO(John Sirois): BundlePayload should expose its sources in a way uniform to
      # SourcesPayload to allow this special-casing to go away.
      if isinstance(target, JvmApp):
        files.update(itertools.chain(*[bundle.filemap.keys() for bundle in target.bundles]))
    return files
