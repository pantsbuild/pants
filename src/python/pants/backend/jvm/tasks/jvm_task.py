# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm import JVM
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.build_graph.build_graph import BuildGraph
from pants.option.custom_types import list_option
from pants.task.task import Task


class JvmTask(Task):

  @classmethod
  def subsystem_dependencies(cls):
    return super(JvmTask, cls).subsystem_dependencies() + (JVM.scoped(cls),)

  @classmethod
  def register_options(cls, register):
    super(JvmTask, cls).register_options(register)
    register('--confs', type=list_option, default=['default'],
             help='Use only these Ivy configurations of external deps.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  def __init__(self, *args, **kwargs):
    super(JvmTask, self).__init__(*args, **kwargs)
    self.jvm = JVM.scoped_instance(self)
    self.jvm_options = self.jvm.get_jvm_options()
    self.args = self.jvm.get_program_args()
    self.confs = self.get_options().confs
    self.synthetic_classpath = self.jvm.get_options().synthetic_classpath

  def classpath(self, targets, classpath_prefix=None, classpath_product=None):
    """Builds a transitive classpath for the given targets.

    Optionally includes a classpath prefix or building from a non-default classpath product.

    :param targets: the targets for which to build the transitive classpath.
    :param classpath_prefix: optional additional entries to prepend to the classpath.
    :param classpath_product: an optional ClasspathProduct from which to build the classpath. if not
    specified, the runtime_classpath will be used.
    :return: a list of classpath strings.
    """
    classpath = list(classpath_prefix) if classpath_prefix else []

    classpath_product = classpath_product or self.context.products.get_data('runtime_classpath')

    closure = BuildGraph.closure(targets, bfs=True)

    classpath_for_targets = ClasspathUtil.classpath(closure, classpath_product, self.confs)
    classpath.extend(classpath_for_targets)
    return classpath
