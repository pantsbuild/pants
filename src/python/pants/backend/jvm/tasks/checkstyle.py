# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs
from pants.util.dirutil import safe_open


CHECKSTYLE_MAIN = 'com.puppycrawl.tools.checkstyle.Main'


class Checkstyle(NailgunTask, JvmToolTaskMixin):
  @staticmethod
  def _is_checked(target):
    return target.is_java and not target.is_synthetic

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(Checkstyle, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("skip"), mkflag("skip", negate=True),
                            dest="checkstyle_skip", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Skip checkstyle.")

  def __init__(self, context, workdir):
    super(Checkstyle, self).__init__(context, workdir)

    self._checkstyle_bootstrap_key = 'checkstyle'
    bootstrap_tools = context.config.getlist('checkstyle', 'bootstrap-tools',
                                             default=[':twitter-checkstyle'])
    self.register_jvm_tool(self._checkstyle_bootstrap_key, bootstrap_tools)

    self._configuration_file = context.config.get('checkstyle', 'configuration')

    self._properties = context.config.getdict('checkstyle', 'properties')
    self._confs = context.config.getlist('checkstyle', 'confs', default=['default'])

  def prepare(self, round_manager):
    # TODO(John Sirois): this is a fake requirement on 'ivy_jar_products' in order to force
    # resolve to run before this phase. Require a new CompileClasspath product to be produced by
    # IvyResolve instead.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('ivy_jar_products')
    round_manager.require_data('exclusives_groups')

  def execute(self):
    if self.context.options.checkstyle_skip:
      return
    targets = self.context.targets(self._is_checked)
    with self.invalidated(targets) as invalidation_check:
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
      sources.update([os.path.join(target.payload.sources_rel_path, source)
                      for source in target.payload.sources if source.endswith('.java')])
    return sources

  def checkstyle(self, sources, targets):
    egroups = self.context.products.get_data('exclusives_groups')
    etag = egroups.get_group_key_for_target(targets[0])
    classpath = self.tool_classpath(self._checkstyle_bootstrap_key)
    cp = egroups.get_classpath_for_group(etag)
    classpath.extend(jar for conf, jar in cp if conf in self._confs)

    args = [
      '-c', self._configuration_file,
      '-f', 'plain'
    ]

    if self._properties:
      properties_file = os.path.join(self.workdir, 'checkstyle.properties')
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
