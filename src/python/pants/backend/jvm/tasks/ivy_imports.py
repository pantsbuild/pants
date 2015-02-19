# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


class IvyImports(IvyTaskMixin, NailgunTask):
  """Resolves all jar files for the import_jar_libraries property on a target.

  Looks for targets that have an ImportJarsMixin.

  One use case is for  JavaProtobufLibrary, which includes imports for jars
  containing .proto files.
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

    resolve_for = self.context.targets(lambda t: isinstance(t, ImportJarsMixin))
    if resolve_for:
      imports_map = self.context.products.get('ivy_imports')
      executor = self.create_java_executor()
      for target in resolve_for:
        jars = target.imported_jars
        self.context.log.info('Mapping import jars for {target}: \n  {jars}'.format(
            target=nice_target_name(target),
            jars='\n  '.join(self._str_jar(s) for s in jars)))
        self.mapjars(imports_map, target, executor, jars=jars)
