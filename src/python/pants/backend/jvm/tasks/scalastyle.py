# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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

  * ``config`` - Optional path of the scalastyle configuration
    file. If not specified, the check will be skipped. If the file
    doesn't exist, the task will throw.
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

  _config_initialized = False
  _scalastyle_config = None
  _scalastyle_excludes = set()

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(Scalastyle, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True),
                            dest="scalastyle_skip", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Skip scalastyle.")

  def __init__(self, *args, **kwargs):
    super(Scalastyle, self).__init__(*args, **kwargs)

    self._initialize_config()
    self._scalastyle_bootstrap_key = 'scalastyle'
    self.register_jvm_tool(self._scalastyle_bootstrap_key, [':scalastyle'])

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def _initialize_config(self):
    self._config_initialized = False

    self._scalastyle_config = self.context.config.get(
      self._CONFIG_SECTION, self._CONFIG_SECTION_CONFIG_OPTION)

    # Scalastyle config setting is optional, if missing it's fine. we'll
    # just skip the check all together.
    if not self._scalastyle_config:
      self.context.log.debug(
        'Unable to get section[%s] option[%s] value in pants.ini. Scalastyle will be skipped.'
          %(self._CONFIG_SECTION, self._CONFIG_SECTION_CONFIG_OPTION))
      return

    # However, if the config setting value is specified, then it must be a valid file.
    if not os.path.exists(self._scalastyle_config):
      raise Config.ConfigError(
        'Scalastyle config file specified in section[%s] option[%s] in pants.ini ' \
        'does not exist: %s' % (self._CONFIG_SECTION,
                                self._CONFIG_SECTION_CONFIG_OPTION,
                                self._scalastyle_config))

    excludes_file = self.context.config.get(
      self._CONFIG_SECTION, self._CONFIG_SECTION_EXCLUDES_OPTION)

    # excludes setting is optional, but if specified, should point a valid file.
    if excludes_file:
      if not os.path.exists(excludes_file):
        raise Config.ConfigError(
          'Scalastyle excludes file specified in section[%s] option[%s] in pants.ini ' \
          'does not exist: %s' % (self._CONFIG_SECTION,
                                  self._CONFIG_SECTION_EXCLUDES_OPTION,
                                  excludes_file))
      with open(excludes_file) as fh:
        for pattern in fh.readlines():
          self._scalastyle_excludes.add(re.compile(pattern.strip()))
          self.context.log.debug('Scalastyle file exclude pattern: %s' % pattern)
    else:
      self.context.log.debug(
        'Unable to get section[%s] option[%s] value in pants.ini. ' \
        'All scala sources will be checked.'
        % (self._CONFIG_SECTION, self._CONFIG_SECTION_EXCLUDES_OPTION))

    self._config_initialized = True

  @property
  def _should_skip(self):
    return not self._config_initialized or self.context.options.scalastyle_skip

  def _get_non_synthetic_scala_targets(self):
    return self.context.targets(
      lambda target: isinstance(target, Target) # QUESTION(Jin Feng) Is this redundant?
                     and target.has_sources(self._SCALA_SOURCE_EXTENSION)
                     and (not target.is_synthetic))

  def _get_non_excluded_scala_sources(self, scala_targets):
    # Get all the sources from the targets with the path relative to build root.
    # QUESTION(Jin Feng) the class description says they should be relative to
    # repo root, which one is it or they're the same?
    scala_sources = list()
    for target in scala_targets:
      scala_sources.extend(target.sources_relative_to_buildroot())

    # make sure only the sources with scala extension stay.
    scala_sources = filter(
      lambda filename: filename.endswith(self._SCALA_SOURCE_EXTENSION),
      scala_sources)

    # filter out all sources matching exclude patterns, if specified in config.
    if self._scalastyle_excludes:
      def filter_excludes(filename):
        for exclude in self._scalastyle_excludes:
          if exclude.match(filename):
            return False
        return True
      scala_sources = filter(filter_excludes, scala_sources)

    return scala_sources

  def execute(self):
    if self._should_skip:
      self.context.log.info('Skipping scalastyle.')
      return

    targets = self._get_non_synthetic_scala_targets()
    self.context.log.debug('Non synthetic scala targets to be checked:')
    for target in targets:
      self.context.log.debug('  %s' % target.address.spec)

    scala_sources = self._get_non_excluded_scala_sources(targets)
    self.context.log.debug('Non excluded scala sources to be checked:')
    for source in scala_sources:
      self.context.log.debug('  %s' % source)

    if scala_sources:
      def call(srcs):
        cp = self.tool_classpath(self._scalastyle_bootstrap_key)
        return self.runjava(classpath=cp,
                            main=self._MAIN,
                            args=['-c', self._scalastyle_config] + srcs)
      result = Xargs(call).execute(scala_sources)
      if result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (Scalastyle._MAIN, result))
