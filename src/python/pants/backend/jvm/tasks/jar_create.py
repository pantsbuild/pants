# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jar_task import JarBuilderTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel


def is_jvm_binary(target):
  return isinstance(target, JvmBinary)


def is_java_library(target):
  return target.has_sources('.java')


def is_scala_library(target):
  return target.has_sources('.scala')


def is_jvm_library(target):
  return (is_java_library(target)
          or is_scala_library(target)
          or (is_jvm_binary(target) and target.has_resources))


class JarCreate(JarBuilderTask):
  """Jars jvm libraries and optionally their sources and their docs."""

  @classmethod
  def register_options(cls, register):
    super(JarCreate, cls).register_options(register)
    register('--compressed', default=True, action='store_true',
             fingerprint=True,
             help='Create compressed jars.')

  @classmethod
  def product_types(cls):
    return ['jars']

  @classmethod
  def prepare(cls, options, round_manager):
    super(JarCreate, cls).prepare(options, round_manager)
    cls.JarBuilder.prepare(round_manager)

  def __init__(self, *args, **kwargs):
    super(JarCreate, self).__init__(*args, **kwargs)

    self.compressed = self.get_options().compressed
    self._jars = {}

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    with self.invalidated(self.context.targets(is_jvm_library)) as invalidation_check:
      with self.context.new_workunit(name='jar-create', labels=[WorkUnitLabel.MULTITOOL]):
        jar_mapping = self.context.products.get('jars')

        for vt in invalidation_check.all_vts:
          jar_name = vt.target.name + '.jar'
          jar_path = os.path.join(vt.results_dir, jar_name)

          def add_jar_to_products():
            jar_mapping.add(vt.target, vt.results_dir).append(jar_name)

          if vt.valid:
            if os.path.exists(jar_path):
              add_jar_to_products()
          else:
            with self.create_jar(vt.target, jar_path) as jarfile:
              with self.create_jar_builder(jarfile) as jar_builder:
                if vt.target in jar_builder.add_target(vt.target):
                  add_jar_to_products()

  @contextmanager
  def create_jar(self, target, path):
    existing = self._jars.setdefault(path, target)
    if target != existing:
      raise TaskError(
          'Duplicate name: target {} tried to write {} already mapped to target {}'
          .format(target, path, existing))
    self._jars[path] = target
    with self.open_jar(path, overwrite=True, compressed=self.compressed) as jar:
      yield jar
