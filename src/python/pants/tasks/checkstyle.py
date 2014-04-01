# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.dirutil import safe_open

from pants.process.xargs import Xargs
from pants.tasks import TaskError
from pants.tasks.nailgun_task import NailgunTask


CHECKSTYLE_MAIN = 'com.puppycrawl.tools.checkstyle.Main'


class Checkstyle(NailgunTask):
  @staticmethod
  def _is_checked(target):
    return target.is_java and not target.is_synthetic

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True),
                            dest="checkstyle_skip", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Skip checkstyle.")

  def __init__(self, context):
    super(Checkstyle, self).__init__(context)

    self._checkstyle_bootstrap_key = 'checkstyle'
    bootstrap_tools = context.config.getlist('checkstyle', 'bootstrap-tools',
                                             default=[':twitter-checkstyle'])
    self._jvm_tool_bootstrapper.register_jvm_tool(self._checkstyle_bootstrap_key, bootstrap_tools)

    self._configuration_file = context.config.get('checkstyle', 'configuration')

    self._work_dir = context.config.get('checkstyle', 'workdir')
    self._properties = context.config.getdict('checkstyle', 'properties')
    self._confs = context.config.getlist('checkstyle', 'confs', default=['default'])
    self.context.products.require_data('exclusives_groups')

  def execute(self, targets):
    if not self.context.options.checkstyle_skip:
      with self.invalidated(filter(Checkstyle._is_checked, targets)) as invalidation_check:
        invalid_targets = []
        for vt in invalidation_check.invalid_vts:
          invalid_targets.extend(vt.targets)
        sources = self.calculate_sources(invalid_targets)
        if sources:
          result = self.checkstyle(sources, invalid_targets)
          if result != 0:
            raise TaskError('java %s ... exited non-zero (%i)' % (CHECKSTYLE_MAIN, result))

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update([os.path.join(target.target_base, source)
                      for source in target.sources if source.endswith('.java')])
    return sources

  def checkstyle(self, sources, targets):
    egroups = self.context.products.get_data('exclusives_groups')
    etag = egroups.get_group_key_for_target(targets[0])
    classpath = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._checkstyle_bootstrap_key)
    cp = egroups.get_classpath_for_group(etag)
    classpath.extend(jar for conf, jar in cp if conf in self._confs)

    args = [
      '-c', self._configuration_file,
      '-f', 'plain'
    ]

    if self._properties:
      properties_file = os.path.join(self._work_dir, 'checkstyle.properties')
      with safe_open(properties_file, 'w') as pf:
        for k, v in self._properties.items():
          pf.write('%s=%s\n' % (k, v))
      args.extend(['-p', properties_file])

    # We've hit known cases of checkstyle command lines being too long for the system so we guard
    # with Xargs since checkstyle does not accept, for example, @argfile style arguments.
    def call(xargs):
      return self.runjava(classpath=classpath, main=CHECKSTYLE_MAIN,
                          args=args + xargs, workunit_name='checkstyle')
    checks = Xargs(call)

    return checks.execute(sources)
