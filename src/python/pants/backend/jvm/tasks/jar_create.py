# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod, abstractproperty
from contextlib import contextmanager

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jar_task import JarBuilderTask
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


class BaseJarCreate(JarBuilderTask):
  """An abstract task to jar jvm libraries and optionally their sources and their docs."""

  @classmethod
  @abstractmethod
  def product_types(cls):
    pass

  @abstractproperty
  def compressed(cls):
    """True to create compressed jars."""
    pass

  @classmethod
  def prepare(cls, options, round_manager):
    super(BaseJarCreate, cls).prepare(options, round_manager)
    cls.JarBuilder.prepare(round_manager)

  @property
  def cache_target_dirs(self):
    return True

  @abstractmethod
  def _add_jar_to_products(self, target, jar_dir, jar_name):
    """Adds the given jar to the products for the given target."""
    pass

  def _prepare_products(self):
    """Performs any pre-execution preparation of products required by subclasses."""
    pass

  def execute(self):
    with self.invalidated(self.context.targets(is_jvm_library)) as invalidation_check:
      with self.context.new_workunit(name='jar-create', labels=[WorkUnitLabel.MULTITOOL]):
        for vt in invalidation_check.all_vts:
          jar_name = vt.target.name + '.jar'
          jar_dir = vt.results_dir
          jar_path = os.path.join(jar_dir, jar_name)

          if vt.valid:
            if os.path.exists(jar_path):
              self._add_jar_to_products(vt.target, jar_dir, jar_name)
          else:
            with self.create_jar(vt.target, jar_path) as jarfile:
              with self.create_jar_builder(jarfile) as jar_builder:
                if vt.target in jar_builder.add_target(vt.target):
                  self._add_jar_to_products(vt.target, jar_dir, jar_name)

  @contextmanager
  def create_jar(self, target, path):
    with self.open_jar(path, overwrite=True, compressed=self.compressed) as jar:
      yield jar


class RemoteJarCreate(BaseJarCreate):
  """Creates compressed jars, usually for remote distribution."""

  @classmethod
  def register_options(cls, register):
    super(RemoteJarCreate, cls).register_options(register)
    register('--compressed', default=True, action='store_true',
             fingerprint=True,
             deprecated_version='0.0.55',
             deprecated_hint='Compressed jars are created automatically when needed.',
             help='Create compressed jars.')

  @classmethod
  def product_types(cls):
    return ['jars']

  def compressed(cls):
    return True

  def _add_jar_to_products(self, target, jar_dir, jar_name):
    jar_mapping = self.context.products.get('jars')
    jar_mapping.add(target, jar_dir).append(jar_name)


class RuntimeJarCreate(BaseJarCreate):
  """Creates uncompressed jars for usage in unit tests and other local execution."""

  @classmethod
  def product_types(cls):
    return ['runtime_classpath']

  def compressed(cls):
    return False

  def _prepare_products(self):
    compile_classpath = self.context.products.get('compile_classpath')
    self.context.products.safe_create_data('runtime_classpath', compile_classpath.copy)

  def _add_jar_to_products(self, target, jar_dir, jar_name):
    runtime_classpath = self.context.products.get('runtime_classpath')
    runtime_classpath.add_for_target(target, [('default', os.path.join(jar_dir, jar_name))])
