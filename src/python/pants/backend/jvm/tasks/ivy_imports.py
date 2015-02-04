# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


class IvyImports(IvyTaskMixin, NailgunTask):
  """Resolves a jar of .proto files for each target in the context which has imports (ie, for each
  JavaProtobufLibrary target).
  """

  _CONFIG_SECTION = 'ivy-imports'

  # TODO https://github.com/pantsbuild/pants/issues/604 product_types start
  @classmethod
  def product_types(cls):
    return ['ivy_imports']
  # TODO https://github.com/pantsbuild/pants/issues/604 product_types finish

  @classmethod
  def prepare(cls, options, round_manager):
    super(IvyImports, cls).prepare(options, round_manager)
    round_manager.require_data('jvm_build_tools_classpath_callbacks')

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def _str_jar(self, jar):
    return 'jar' + str((jar.org, jar.name, jar.rev))

  def execute(self):
    def nice_target_name(t):
      return t.address.spec

    resolve_for = self.context.targets(lambda t: t.has_label('has_imports'))
    if resolve_for:
      imports_map = self.context.products.get('ivy_imports')
      executor = self.create_java_executor()
      for target in resolve_for:
        jars = target.imports
        self.context.log.info('Mapping import jars for {target}: \n  {jars}'.format(
            target=nice_target_name(target),
            jars='\n  '.join(self._str_jar(s) for s in jars)))
        self.mapjars(imports_map, target, executor, jars=jars)
