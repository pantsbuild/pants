# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.process.xargs import Xargs


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


class Scalastyle(NailgunTask, JvmToolTaskMixin):
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
    register('--skip', action='store_true', help='Skip scalastyle.')
    register('--config', advanced=True, help='Path to scalastyle config file.')
    register('--excludes', advanced=True,
             help='Path to optional scalastyle excludes file. Each line is a regex. (Blank lines '
                  'and lines starting with \'#\' are ignored.) A file is skipped if its path '
                  '(relative to the repo root) matches any of these regexes.')
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


  def execute(self):
    if self.get_options().skip:
      self.context.log.info('Skipping scalastyle.')
      return

    # Don't even try and validate options if we're irrelevant.
    targets = self.get_non_synthetic_scala_targets(self.context.targets())
    if not targets:
      return

    scalastyle_config = self.validate_scalastyle_config()
    scalastyle_excluder = self.create_file_excluder()

    self.context.log.debug('Non synthetic scala targets to be checked:')
    for target in targets:
      self.context.log.debug('  {address_spec}'.format(address_spec=target.address.spec))

    scala_sources = self.get_non_excluded_scala_sources(scalastyle_excluder, targets)
    self.context.log.debug('Non excluded scala sources to be checked:')
    for source in scala_sources:
      self.context.log.debug('  {source}'.format(source=source))

    if scala_sources:
      def call(srcs):
        cp = self.tool_classpath('scalastyle')
        return self.runjava(classpath=cp,
                            main=self._MAIN,
                            jvm_options=self.get_options().jvm_options,
                            args=['-c', scalastyle_config] + srcs)
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
