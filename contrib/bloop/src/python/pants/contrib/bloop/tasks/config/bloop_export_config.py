# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.base.build_environment import get_buildroot
from pants.java.distribution.distribution import DistributionLocator
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized_property
from pants.util.meta import classproperty
from pants.util.objects import datatype, string_list, string_type

from pants.contrib.bloop.tasks.config.modified_export_task_base import ModifiedExportTaskBase


class BloopExportConfig(ModifiedExportTaskBase):

  class BloopExport(datatype([
      ('exported_targets_map', dict),
      ('reported_scala_version', string_type),
      ('scala_compiler_jars', string_list),
      ('pants_target_types', string_list),
  ])): pass

  @classmethod
  def product_types(cls):
    return [cls.BloopExport]

  @classproperty
  def relevant_target_types(cls):
    """???"""
    return [
      "scala_library",
      "java_library",
      "junit_tests",
      "jvm_binary",
      "target",
      "annotation_processor",
    ]

  @classmethod
  def register_options(cls, register):
    super(BloopExportConfig, cls).register_options(register)

    register('--reported-scala-version', type=text_type, default='2.12.8',
             help='Scala version to report to ensime. Defaults to the scala platform version.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopExportConfig, cls).prepare(options, round_manager)
    # NB: this is so we run after compile -- we want our class dirs to be populated already.
    round_manager.require_data('runtime_classpath')
    # round_manager.require_data(BloopExportConfigJar)
    # cls.prepare_tools(round_manager)

  @classmethod
  def subsystem_dependencies(cls):
    return super(BloopExportConfig, cls).subsystem_dependencies() + (DistributionLocator, ScalaPlatform,)

  @memoized_property
  def _scala_platform(self):
    return ScalaPlatform.global_instance()

  def execute(self):
    exported_targets_map = self.generate_targets_map(self.context.targets())
    # self.context.log.debug('exported_targets_map: {}'.format(exported_targets_map))

    # TODO: use JvmPlatform for jvm options!
    reported_scala_version = self.get_options().reported_scala_version
    if not reported_scala_version:
      reported_scala_version = self._scala_platform.version

    scala_compiler_jars = [
      text_type(fast_relpath(cpe.path, get_buildroot())) for cpe in
      self._scala_platform.compiler_classpath_entries(self.context.products, self.context._scheduler)
    ]

    export_config = self.BloopExport(
      exported_targets_map=exported_targets_map,
      reported_scala_version=reported_scala_version,
      scala_compiler_jars=scala_compiler_jars,
      pants_target_types=self.relevant_target_types,
    )

    self.context.products.register_data(self.BloopExport, export_config)
