# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_walk


class IvyImports(IvyTaskMixin, NailgunTask):
  """Resolves all jar files for the import_jar_libraries property on a target.

  Looks for targets that have an ImportJarsMixin.

  One use case is for  JavaProtobufLibrary, which includes imports for jars
  containing .proto files.
  """

  # TODO https://github.com/pantsbuild/pants/issues/604 product_types start
  @classmethod
  def product_types(cls):
    # TODO(mateor) Create a more robust ivy_import product, that exposes the path to the jar
    # and a slot for the metadata from the IvyModuleRef:
    # https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/ivy_utils.py#L38-38
    return ['ivy_imports']  # Guaranteed to populate target => { builddir: [jar_filenames]}
  # TODO https://github.com/pantsbuild/pants/issues/604 product_types finish

  @classmethod
  def prepare(cls, options, round_manager):
    super(IvyImports, cls).prepare(options, round_manager)
    round_manager.require_data('jvm_build_tools_classpath_callbacks')

  def _str_jar(self, jar):
    return 'jar' + str((jar.org, jar.name, jar.rev))

  def _is_invalid(self, invalid_targets, unpacked_jars_target):
    """Check to see if the UnpackedJar or its dependent JarLibraries are invalid.

    :param invalid_targets:  Invalid targets returned from invalidation check
    :param unpacked_jars_target:  The unpacked_jar target
    :return: True if one of the targets has been invalidated.
    """
    if unpacked_jars_target in invalid_targets:
      return True
    for library in unpacked_jars_target.imported_jar_libraries:
      if library in invalid_targets:
        return True
    return False

  def execute(self):
    # Gather all targets that are both capable of importing jars and actually
    # declare some imports.
    targets = self.context.targets(lambda t: isinstance(t, ImportJarsMixin)
                                             and t.imported_jar_libraries)
    if not targets:
      return None
    imports_map = self.context.products.get('ivy_imports')
    executor = self.create_java_executor()

    # Create a list of all of these targets plus the list of JarDependencies
    # they depend on.
    all_targets = set(targets)
    for target in targets:
      all_targets.update(target.imported_jar_libraries)

    imported_targets = []

    with self.invalidated(all_targets, invalidate_dependents=True) as invalidation_check:
      invalid_targets = []
      if invalidation_check.invalid_vts:
        invalid_targets += [vt.target for vt in invalidation_check.invalid_vts]
      for target in targets:
        if self._is_invalid(invalid_targets, target):
          jars = target.imported_jars
          self.context.log.info('Mapping import jars for {target}: \n  {jars}'.format(
            target=target.address.spec,
            jars='\n  '.join(self._str_jar(s) for s in jars)))
          self.mapjars(imports_map, target, executor, jars=jars)
          imported_targets.append(target)

    # Reconstruct the ivy_imports target -> mapdir  mapping for targets that are
    # valid from walking the build cache
    cached_targets = set(targets) - set(invalid_targets)
    for import_jars_target in cached_targets:
      mapdir = self.mapjar_workdir(import_jars_target)
      for root, _, files in  safe_walk(mapdir):
        jarfiles = []
        for f in files:
          # We only expect ivy to touch this directory, so it should be just a directory with the
          # ivy output.  However, Ivy will stick an 'ivy.xml' file here which we don't want to map.
          if f != 'ivy.xml':
            full_filename = os.path.join(root, f)
            if os.path.islink(full_filename):
              jarfiles.append(f)
            else:
              raise TaskError('ivy-imports found unexpected file in ivy output directory: {}'
                              .format(full_filename))
        if jarfiles:
          imports_map.add(import_jars_target, root, jarfiles)

    # Returning the list of imported targets for testing purposes
    return imported_targets
