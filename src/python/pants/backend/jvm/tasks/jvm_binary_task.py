# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from twitter.common.collections.orderedset import OrderedSet

from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jar_task import JarBuilderTask
from pants.base.exceptions import TaskError
from pants.java.util import execute_runner
from pants.util.contextutil import temporary_dir
from pants.util.fileutil import atomic_copy
from pants.util.memo import memoized_property


class JvmBinaryTask(JarBuilderTask):

  @staticmethod
  def is_binary(target):
    return isinstance(target, JvmBinary)

  @staticmethod
  def add_main_manifest_entry(jar, binary):
    """Creates a jar manifest for the given binary.

    If the binary declares a main then a 'Main-Class' manifest entry will be included.
    """
    main = binary.main
    if main is not None:
      jar.main(main)

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmBinaryTask, cls).prepare(options, round_manager)
    round_manager.require_data('compile_classpath')
    Shader.Factory.prepare_tools(round_manager)

  @classmethod
  def subsystem_dependencies(cls):
    return super(JvmBinaryTask, cls).subsystem_dependencies() + (Shader.Factory,)

  def list_external_jar_dependencies(self, binary, confs=None):
    """Returns the external jar dependencies of the given binary.

    :param binary: The jvm binary target to list transitive external dependencies for.
    :type binary: :class:`pants.backend.jvm.targets.jvm_binary.JvmBinary`
    :param confs: The ivy configurations to include in the dependencies list, ('default',) by
                  default.
    :type confs: :class:`collections.Iterable` of string
    :returns: A list of (jar path, coordinate) tuples.
    :rtype: list of (string, :class:`pants.backend.jvm.jar_dependency_utils.M2Coordinate`)
    """
    classpath_products = self.context.products.get_data('compile_classpath')
    classpath_entries = classpath_products.get_artifact_classpath_entries_for_targets([binary])
    confs = confs or ('default',)
    external_jars = OrderedSet(jar_entry for conf, jar_entry in classpath_entries if conf in confs)
    return [(entry.path, entry.coordinate) for entry in external_jars
            if not entry.is_excluded_by(binary.deploy_excludes)]

  @contextmanager
  def monolithic_jar(self, binary, path, with_external_deps):
    """Creates a jar containing the class files for a jvm_binary target and all its deps.

    Yields a handle to the open jarfile, so the caller can add to the jar if needed.

    :param binary: The jvm_binary target to operate on.
    :param path: Write the output jar here, overwriting an existing file, if any.
    :param with_external_deps: If True, unpack external jar deps and add their classes to the jar.
    """
    # TODO(benjy): There's actually nothing here that requires 'binary' to be a jvm_binary.
    # It could be any target. And that might actually be useful.
    with self.context.new_workunit(name='create-monolithic-jar'):
      with self.open_jar(path,
                         jar_rules=binary.deploy_jar_rules,
                         overwrite=True,
                         compressed=True) as monolithic_jar:

        with self.context.new_workunit(name='add-internal-classes'):
          with self.create_jar_builder(monolithic_jar) as jar_builder:
            jar_builder.add_target(binary, recursive=True)

        if with_external_deps:
          # NB(gmalmquist): Shading each jar dependency with its own prefix would be a nice feature,
          # but is not currently possible with how things are set up. It may not be possible to do
          # in general, at least efficiently.
          with self.context.new_workunit(name='add-dependency-jars'):
            dependencies = self.list_external_jar_dependencies(binary)
            for jar, coordinate in dependencies:
              self.context.log.debug('  dumping {} from {}'.format(coordinate, jar))
              monolithic_jar.writejar(jar)

        yield monolithic_jar

      if binary.shading_rules:
        with self.context.new_workunit('shade-monolithic-jar'):
          self.shade_jar(binary=binary, jar_id=binary.address.reference(), jar_path=path)

  @memoized_property
  def shader(self):
    return Shader.Factory.create(self.context)

  def shade_jar(self, binary, jar_id, jar_path):
    """Shades a jar using the shading rules from the given jvm_binary.

    This *overwrites* the existing jar file at ``jar_path``.

    :param binary: The jvm_binary target the jar is being shaded for.
    :param jar_id: The id of the jar being shaded (used for logging).
    :param jar_path: The filepath to the jar that should be shaded.
    """
    self.context.log.debug('Shading {} at {}.'.format(jar_id, jar_path))
    with temporary_dir() as tempdir:
      output_jar = os.path.join(tempdir, os.path.basename(jar_path))
      rules = [rule.rule() for rule in binary.shading_rules]
      with self.shader.binary_shader_for_rules(output_jar, jar_path, rules) as shade_runner:
        result = execute_runner(shade_runner, workunit_factory=self.context.new_workunit,
                                workunit_name='jarjar')
        if result != 0:
          raise TaskError('Shading tool failed to shade {0} (error code {1})'.format(jar_path,
                                                                                     result))
        if not os.path.exists(output_jar):
          raise TaskError('Shading tool returned success for {0}, but '
                          'the output jar was not found at {1}'.format(jar_path, output_jar))
        atomic_copy(output_jar, jar_path)
        return jar_path
