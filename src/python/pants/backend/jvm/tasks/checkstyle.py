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

  _CONFIG_SECTION = 'checkstyle'

  @staticmethod
  def _is_checked(target):
    return target.is_java and not target.is_synthetic

  @classmethod
  def register_options(cls, register):
    super(Checkstyle, cls).register_options(register)
    register('--skip', action='store_true', help='Skip checkstyle.')
    register('--configuration', help='Path to the checkstyle configuration file.')
    register('--suppression_files', default=[],
             help='List of checkstyle supression configuration files.')
    register('--properties', default={},
             help='Dictionary of property mappings to use for checkstyle.properties.')
    register('--confs', default=['default'],
             help='One or more ivy configurations to resolve for this target. This parameter is '
                  'not intended for general use. ')
    register('--bootstrap-tools', default=['//:twitter-checkstyle'],
             help='Pants targets used to bootstrap this tool.')

  def __init__(self, *args, **kwargs):
    super(Checkstyle, self).__init__(*args, **kwargs)

    self._checkstyle_bootstrap_key = 'checkstyle'
    self.register_jvm_tool(self._checkstyle_bootstrap_key, self.get_options().bootstrap_tools,
                           ini_section=self.options_scope,
                           ini_key='bootstrap-tools')

    suppression_files = self.get_options().supression_files
    self._properties = self.get_options().properties
    self._properties['checkstyle.suppression.files'] = ','.join(suppression_files)
    self._confs = self.context.config.getlist(self._CONFIG_SECTION, 'confs', )

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    # TODO(John Sirois): this is a fake requirement on 'ivy_jar_products' in order to force
    # resolve to run before this goal. Require a new CompileClasspath product to be produced by
    # IvyResolve instead.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('ivy_jar_products')
    round_manager.require_data('exclusives_groups')

  def execute(self):
    if self.get_options().skip:
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
      sources.update(source for source in target.sources_relative_to_buildroot()
                     if source.endswith('.java'))
    return sources

  def checkstyle(self, sources, targets):
    egroups = self.context.products.get_data('exclusives_groups')
    etag = egroups.get_group_key_for_target(targets[0])
    classpath = self.tool_classpath(self._checkstyle_bootstrap_key)
    cp = egroups.get_classpath_for_group(etag)
    classpath.extend(jar for conf, jar in cp if conf in self.get_options().confs)

    args = [
      '-c', self.get_options().configuration,
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
