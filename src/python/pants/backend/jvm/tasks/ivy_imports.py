# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.tasks.classpath_products import ArtifactClasspathEntry, ClasspathProducts
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


class IvyImports(IvyTaskMixin, NailgunTask):
  """Resolves all jar files for the import_jar_libraries property on all `ImportJarsMixin` targets.

  One use case is for  JavaProtobufLibrary, which includes imports for jars containing .proto files.
  """

  # TODO https://github.com/pantsbuild/pants/issues/604 product_types start
  @classmethod
  def product_types(cls):
    return [JarImportProducts]
  # TODO https://github.com/pantsbuild/pants/issues/604 product_types finish

  @staticmethod
  def has_imports(target):
    return isinstance(target, ImportJarsMixin) and target.imported_jar_libraries

  def execute(self):
    jar_import_products = self.context.products.get_data(JarImportProducts,
                                                         init_func=JarImportProducts)

    # Gather all targets that are both capable of importing jars and actually declare some imports.
    targets = self.context.targets(predicate=self.has_imports)
    if not targets:
      return

    # Create a list of all of these targets plus the list of JarDependencies they depend on.
    all_targets = set(targets)
    for target in targets:
      all_targets.update(target.imported_jar_libraries)

    imports_classpath = ClasspathProducts()
    self.resolve(executor=self.create_java_executor(),
                 targets=all_targets,
                 classpath_products=imports_classpath,
                 invalidate_dependents=True)

    for target in targets:
      cp_entries = imports_classpath.get_classpath_entries_for_targets((target,))
      for conf, cp_entry in cp_entries:
        if isinstance(cp_entry, ArtifactClasspathEntry):
          jar_import_products.imported(target, cp_entry.coordinate, cp_entry.path)
