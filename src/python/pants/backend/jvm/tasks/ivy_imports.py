# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


class ImportsUtil(IvyUtils):
  def __init__(self, context):
    super(ImportsUtil, self).__init__(context.config, context.options, context.log)

  def is_mappable_artifact(self, org, name, path):
    return path.endswith('.jar') and super(ImportsUtil, self).is_mappable_artifact(org, name, path)

  def mapto_dir(self):
    return os.path.join(self._workdir, 'mapped-imports')


class IvyImports(NailgunTask):
  """Resolves a jar of .proto files for each target in the context which has imports (ie, for each
  JavaProtobufLibrary target).
  """

  _CONFIG_SECTION = 'ivy-imports'

  @classmethod
  def product_types(cls):
    return ['ivy_imports']

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    super(IvyImports, self).prepare(round_manager)
    round_manager.require_data('jvm_build_tools_classpath_callbacks')

  def _str_jar(self, jar):
    return 'jar' + str((jar.org, jar.name, jar.rev))

  def execute(self):
    def nice_target_name(t):
      return t.address.spec

    resolve_for = self.context.targets(lambda t: t.has_label('has_imports'))
    if resolve_for:
      imports_util = ImportsUtil(self.context)
      imports_map = self.context.products.get('ivy_imports')
      executor = self.create_java_executor()
      for target in resolve_for:
        jars = target.imports
        self.context.log.info('Mapping import jars for {target}: \n  {jars}'.format(
            target=nice_target_name(target),
            jars='\n  '.join(self._str_jar(s) for s in jars)))
        imports_util.mapjars(imports_map, target, executor,
                             workunit_factory=self.context.new_workunit,
                             jars=jars)
