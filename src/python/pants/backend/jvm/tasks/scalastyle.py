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

  Scalastyle is configured via the 'scalastyle' pants.ini section.

  * ``config`` - Required path of the scalastyle configuration file.
  * ``excludes`` - Optional path of an excludes file that contains
    lines of regular expressions used to exclude matching files
    from style checks. File names matched against these regular
    expressions are relative to the repository root
    (e.g.: com/twitter/mybird/MyBird.scala).
  """

  _CONFIG_SECTION = 'scalastyle'
  _MAIN = 'org.scalastyle.Main'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(Scalastyle, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True),
                            dest="scalastyle_skip", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Skip scalastyle.")

  def __init__(self, *args, **kwargs):
    super(Scalastyle, self).__init__(*args, **kwargs)
    self._scalastyle_config = self.context.config.get_required(self._CONFIG_SECTION, 'config')
    if not os.path.exists(self._scalastyle_config):
      raise Config.ConfigError(
          'Scalastyle config file does not exist: %s' % self._scalastyle_config)

    excludes_file = self.context.config.get(self._CONFIG_SECTION, 'excludes')
    self._excludes = set()
    if excludes_file:
      if not os.path.exists(excludes_file):
        raise Config.ConfigError('Scalastyle excludes file does not exist: %s' % excludes_file)
      self.context.log.debug('Using scalastyle excludes file %s' % excludes_file)
      with open(excludes_file) as fh:
        for pattern in fh.readlines():
          self._excludes.add(re.compile(pattern.strip()))

    self._scalastyle_bootstrap_key = 'scalastyle'
    self.register_jvm_tool(self._scalastyle_bootstrap_key, [':scalastyle'])

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def execute(self):
    if self.context.options.scalastyle_skip:
      self.context.log.debug('Skipping checkstyle.')
      return

    check_targets = list()
    targets = self.context.targets()
    for target in targets:
      for tgt in target.resolve():
        if isinstance(tgt, Target) and tgt.has_sources('.scala'):
          check_targets.append(tgt)

    def filter_excludes(filename):
      if self._excludes:
        for exclude in self._excludes:
          if exclude.match(filename):
            return False
      return True

    scala_sources = list()
    for target in check_targets:
      def collect(filename):
        if filename.endswith('.scala'):
          scala_sources.append(os.path.join(target.target_base, filename))
      map(collect, filter(filter_excludes, target.sources))

    if scala_sources:
      def call(srcs):
        cp = self.tool_classpath(self._scalastyle_bootstrap_key)
        return self.runjava(classpath=cp,
                            main=self._MAIN,
                            args=['-c', self._scalastyle_config] + srcs)
      result = Xargs(call).execute(scala_sources)
      if result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (Scalastyle._MAIN, result))
