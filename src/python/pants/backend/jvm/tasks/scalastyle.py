# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.option.custom_types import file_option
from pants.process.xargs import Xargs
from pants.util.dirutil import touch


# TODO: Move somewhere more general?
class FileExcluder(object):
  def __init__(self, excludes_path, log):
    self.excludes = set()
    if excludes_path:
      if not os.path.exists(excludes_path):
        raise TaskError('Excludes file does not exist: {0}'.format(excludes_path))
      with open(excludes_path) as fh:
        for line in fh.readlines():
          pattern = line.strip()
          if pattern and not pattern.startswith('#'):
            self.excludes.add(re.compile(pattern))
            log.debug('Exclude pattern: {pattern}'.format(pattern=pattern))
    else:
      log.debug('No excludes file specified. All scala sources will be checked.')

  def should_include(self, source_filename):
    for exclude in self.excludes:
      if exclude.match(source_filename):
        return False
    return True


class Scalastyle(NailgunTask):
  """Checks scala source files to ensure they're stylish.

  Scalastyle only checks scala sources in non-synthetic targets.
  """

  class UnspecifiedConfig(TaskError):
    def __init__(self):
      super(Scalastyle.UnspecifiedConfig, self).__init__(
        'Path to scalastyle config file must be specified.')

  class MissingConfig(TaskError):
    def __init__(self, path):
      super(Scalastyle.MissingConfig, self).__init__(
        'Scalastyle config file does not exist: {0}.'.format(path))

  _SCALA_SOURCE_EXTENSION = '.scala'

  _MAIN = 'org.scalastyle.Main'

  @classmethod
  def register_options(cls, register):
    super(Scalastyle, cls).register_options(register)
    register('--skip', action='store_true', fingerprint=True, help='Skip scalastyle.')
    register('--config', type=file_option, advanced=True, fingerprint=True,
             help='Path to scalastyle config file.')
    register('--excludes', type=file_option, advanced=True, fingerprint=True,
             help='Path to optional scalastyle excludes file. Each line is a regex. (Blank lines '
                  'and lines starting with \'#\' are ignored.) A file is skipped if its path '
                  '(relative to the repo root) matches any of these regexes.')
    register('--jvm-options', action='append', metavar='<option>...', advanced=True,
             help='Run scalastyle with these extra jvm options.')
    register('--verbose', action='store_true', default=False,
             help='Enable verbose scalastyle output.')
    register('--quiet', action='store_true', default=False,
             help='Silence scalastyle error messages.')
    cls.register_jvm_tool(register, 'scalastyle')

  @classmethod
  def get_non_synthetic_scala_targets(cls, targets):
    return filter(
      lambda target: isinstance(target, Target)
                     and target.has_sources(cls._SCALA_SOURCE_EXTENSION)
                     and (not target.is_synthetic),
      targets)

  @classmethod
  def get_non_excluded_scala_sources(cls, scalastyle_excluder, scala_targets):
    # Get all the sources from the targets with the path relative to build root.
    scala_sources = list()
    for target in scala_targets:
      scala_sources.extend(target.sources_relative_to_buildroot())

    # make sure only the sources with the .scala extension stay.
    scala_sources = filter(
      lambda filename: filename.endswith(cls._SCALA_SOURCE_EXTENSION),
      scala_sources)

    # filter out all sources matching exclude patterns, if specified in config.
    scala_sources = filter(scalastyle_excluder.should_include, scala_sources)

    return scala_sources

  def __init__(self, *args, **kwargs):
    super(Scalastyle, self).__init__(*args, **kwargs)

    self._results_dir = os.path.join(self.workdir, 'results')

  def _create_result_file(self, target):
    result_file = os.path.join(self._results_dir, target.id)
    touch(result_file)
    return result_file

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    if self.get_options().skip:
      self.context.log.info('Skipping scalastyle.')
      return

    # Don't even try and validate options if we're irrelevant.
    targets = self.get_non_synthetic_scala_targets(self.context.targets())
    if not targets:
      return

    with self.invalidated(targets) as invalidation_check:
      invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]

      scalastyle_config = self.validate_scalastyle_config()
      scalastyle_verbose = self.get_options().verbose
      scalastyle_quiet = self.get_options().quiet
      scalastyle_excluder = self.create_file_excluder()

      self.context.log.debug('Non synthetic scala targets to be checked:')
      for target in invalid_targets:
        self.context.log.debug('  {address_spec}'.format(address_spec=target.address.spec))

      scala_sources = self.get_non_excluded_scala_sources(scalastyle_excluder, invalid_targets)
      self.context.log.debug('Non excluded scala sources to be checked:')
      for source in scala_sources:
        self.context.log.debug('  {source}'.format(source=source))

      if scala_sources:
        def call(srcs):
          def to_java_boolean(x):
            return str(x).lower()

          cp = self.tool_classpath('scalastyle')
          scalastyle_args = [
            '-c', scalastyle_config,
            '-v', to_java_boolean(scalastyle_verbose),
            '-q', to_java_boolean(scalastyle_quiet),
            ]
          return self.runjava(classpath=cp,
                              main=self._MAIN,
                              jvm_options=self.get_options().jvm_options,
                              args=scalastyle_args + srcs)

        result = Xargs(call).execute(scala_sources)
        if result != 0:
          raise TaskError('java {entry} ... exited non-zero ({exit_code})'.format(
            entry=Scalastyle._MAIN, exit_code=result))

  def validate_scalastyle_config(self):
    scalastyle_config = self.get_options().config
    if not scalastyle_config:
      raise Scalastyle.UnspecifiedConfig()
    if not os.path.exists(scalastyle_config):
      raise Scalastyle.MissingConfig(scalastyle_config)
    return scalastyle_config

  def create_file_excluder(self):
    return FileExcluder(self.get_options().excludes, self.context.log)
