# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.config import Config
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.process.xargs import Xargs


class Scalastyle(NailgunTask, JvmToolTaskMixin):
  """Checks scala source files to ensure they're stylish.

  Scalastyle only checks against scala sources in non-synthetic
  targets.

  Scalastyle is configured via the 'scalastyle' pants.ini section.

  * ``config`` - Required path of the scalastyle configuration
    file. If the file doesn't exist, the task will throw.
  * ``excludes`` - Optional path of an excludes file that contains
    lines of regular expressions used to exclude matching files
    from style checks. File names matched against these regular
    expressions are relative to the repository root
    (e.g.: com/twitter/mybird/MyBird.scala). If not specified,
    all scala sources in the targets will be checked. If the file
    doesn't exist, the task will throw.
  """

  _CONFIG_SECTION = 'scalastyle'
  _CONFIG_SECTION_CONFIG_OPTION = 'config'
  _CONFIG_SECTION_EXCLUDES_OPTION = 'excludes'
  _SCALA_SOURCE_EXTENSION = '.scala'

  _MAIN = 'org.scalastyle.Main'

  _scalastyle_config = None
  _scalastyle_excludes = None

  @classmethod
  def register_options(cls, register):
    super(Scalastyle, cls).register_options(register)
    register('--skip', action='store_true', help='Skip scalastyle.')
    cls.register_jvm_tool(register, 'scalastyle')

  def __init__(self, *args, **kwargs):
    super(Scalastyle, self).__init__(*args, **kwargs)
    self._initialize_config()

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def _initialize_config(self):
    scalastyle_config = self.context.config.get(
      self._CONFIG_SECTION, self._CONFIG_SECTION_CONFIG_OPTION)

    # Scalastyle task by default isn't wired up in pants, but if it is installed
    # via plugin, then the config file setting is required.
    if not scalastyle_config:
      raise Config.ConfigError(
        'Scalastyle config is missing from section[{section}] option[{setting}] in '
        'pants.ini.'.format(
          section=self._CONFIG_SECTION,
          setting=self._CONFIG_SECTION_CONFIG_OPTION))

    # And the config setting value must be a valid file.
    if not os.path.exists(scalastyle_config):
      raise Config.ConfigError(
        'Scalastyle config file specified in section[{section}] option[{setting}] in pants.ini '
        'does not exist: {file}'.format(
          section=self._CONFIG_SECTION,
          setting=self._CONFIG_SECTION_CONFIG_OPTION,
          file=scalastyle_config))

    excludes_file = self.context.config.get(
      self._CONFIG_SECTION, self._CONFIG_SECTION_EXCLUDES_OPTION)

    scalastyle_excludes = set()
    if excludes_file:
      # excludes setting is optional, but if specified, must be a valid file.
      if not os.path.exists(excludes_file):
        raise Config.ConfigError(
          'Scalastyle excludes file specified in section[{section}] option[{setting}] in '
          'pants.ini does not exist: {file}'.format(
            section=self._CONFIG_SECTION,
            setting=self._CONFIG_SECTION_EXCLUDES_OPTION,
            file=excludes_file))
      with open(excludes_file) as fh:
        for pattern in fh.readlines():
          scalastyle_excludes.add(re.compile(pattern.strip()))
          self.context.log.debug(
            'Scalastyle file exclude pattern: {pattern}'.format(pattern=pattern))
    else:
      # excludes setting is optional.
      self.context.log.debug(
        'Unable to get section[{section}] option[{setting}] value in pants.ini. '
        'All scala sources will be checked.'.format(
          section=self._CONFIG_SECTION, setting=self._CONFIG_SECTION_EXCLUDES_OPTION))

    # Only transfer to local variables to the state at the end to minimize side effects.
    self._scalastyle_config = scalastyle_config or None
    self._scalastyle_excludes = scalastyle_excludes or None

  @property
  def _should_skip(self):
    return self.get_options().skip

  def _get_non_synthetic_scala_targets(self, targets):
    return filter(
      lambda target: isinstance(target, Target)
                     and target.has_sources(self._SCALA_SOURCE_EXTENSION)
                     and (not target.is_synthetic),
      targets)

  def _should_include_source(self, source_filename):
    if not self._scalastyle_excludes:
      return True
    for exclude in self._scalastyle_excludes:
      if exclude.match(source_filename):
        return False
    return True

  def _get_non_excluded_scala_sources(self, scala_targets):
    # Get all the sources from the targets with the path relative to build root.
    scala_sources = list()
    for target in scala_targets:
      scala_sources.extend(target.sources_relative_to_buildroot())

    # make sure only the sources with scala extension stay.
    scala_sources = filter(
      lambda filename: filename.endswith(self._SCALA_SOURCE_EXTENSION),
      scala_sources)

    # filter out all sources matching exclude patterns, if specified in config.
    scala_sources = filter(self._should_include_source, scala_sources)

    return scala_sources

  def execute(self):
    if self._should_skip:
      self.context.log.info('Skipping scalastyle.')
      return

    targets = self._get_non_synthetic_scala_targets(self.context.targets())
    self.context.log.debug('Non synthetic scala targets to be checked:')
    for target in targets:
      self.context.log.debug('  {address_spec}'.format(address_spec=target.address.spec))

    scala_sources = self._get_non_excluded_scala_sources(targets)
    self.context.log.debug('Non excluded scala sources to be checked:')
    for source in scala_sources:
      self.context.log.debug('  {source}'.format(source=source))

    if scala_sources:
      def call(srcs):
        cp = self.tool_classpath('scalastyle')
        return self.runjava(classpath=cp,
                            main=self._MAIN,
                            args=['-c', self._scalastyle_config] + srcs)
      result = Xargs(call).execute(scala_sources)
      if result != 0:
        raise TaskError('java {entry} ... exited non-zero ({exit_code})'.format(
          entry=Scalastyle._MAIN, exit_code=result))
