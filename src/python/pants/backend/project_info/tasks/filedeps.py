# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.build_environment import get_buildroot


class FileDeps(ConsoleTask):
  """List all transitive file dependencies of the targets specified on the command line.

  Files are listed with absolute paths and any BUILD files implied in the transitive closure of
  targets are also included.
  """

  @classmethod
  def register_options(cls, register):
    super(FileDeps, cls).register_options(register)
    register('--globs', default=False, action='store_true',
             help='Instead of outputting filenames, output globs (ignoring excludes)')

  def console_output(self, targets):
    concrete_targets = set()
    for target in targets:
      concrete_target = target.concrete_derived_from
      concrete_targets.add(concrete_target)
      # TODO(John Sirois): This hacks around ScalaLibraries' psuedo-deps on JavaLibraries.  We've
      # already tried to tuck away this hack by subclassing closure() in ScalaLibrary - but in this
      # case that's not enough when a ScalaLibrary with java_sources is an interior node of the
      # active context graph.  This awkwardness should be eliminated when ScalaLibrary can point
      # to a java source set as part of its 1st class sources.
      if isinstance(concrete_target, ScalaLibrary):
        concrete_targets.update(concrete_target.java_sources)

    buildroot = get_buildroot()
    files = set()
    output_globs = self.get_options().globs
    for target in concrete_targets:
      files.add(target.address.build_file.full_path)
      if output_globs or target.has_sources():
        if output_globs:
          globs_obj = target.globs_relative_to_buildroot()
          if globs_obj:
            files.update(os.path.join(buildroot, src) for src in globs_obj['globs'])
        else:
          files.update(os.path.join(buildroot, src) for src in target.sources_relative_to_buildroot())
      # TODO(John Sirois): BundlePayload should expose its sources in a way uniform to
      # SourcesPayload to allow this special-casing to go away.
      if isinstance(target, JvmApp) and not output_globs:
        files.update(itertools.chain(*[bundle.filemap.keys() for bundle in target.bundles]))
    return files
