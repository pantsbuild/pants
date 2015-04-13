# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.fs.fs import safe_filename
from pants.util.dirutil import safe_mkdir


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


def jarname(target, extension='.jar'):
  # TODO(John Sirois): incorporate version
  _, id_, _ = target.get_artifact_info()
  # Cap jar names quite a bit lower than the standard fs limit of 255 characters since these
  # artifacts will often be used outside pants and those uses may manipulate (expand) the jar
  # filenames blindly.
  return safe_filename(id_, extension, max_length=200)


class JarCreate(JarTask):
  """Jars jvm libraries and optionally their sources and their docs."""

  @classmethod
  def register_options(cls, register):
    super(JarCreate, cls).register_options(register)
    register('--compressed', default=True, action='store_true',
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

  def execute(self):
    safe_mkdir(self.workdir)

    with self.context.new_workunit(name='jar-create', labels=[WorkUnit.MULTITOOL]):
      for target in self.context.targets(is_jvm_library):
        jar_name = jarname(target)
        jar_path = os.path.join(self.workdir, jar_name)
        with self.create_jar(target, jar_path) as jarfile:
          jar_builder = self.create_jar_builder(jarfile)
          if target in jar_builder.add_target(target):
            self.context.products.get('jars').add(target, self.workdir).append(jar_name)

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
