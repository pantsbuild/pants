# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os

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
  def setup_parser(cls, option_group, args, mkflag):
    super(JarCreate, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('compressed'), mkflag('compressed', negate=True),
                            dest='jar_create_compressed', default=True,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Create compressed jars.')

  @classmethod
  def product_types(cls):
    return ['jars']

  def __init__(self, context, workdir):
    super(JarCreate, self).__init__(context, workdir)

    self.compressed = context.options.jar_create_compressed
    self._jar_builder = self.prepare_jar_builder()
    self._jars = {}

  def execute(self):
    safe_mkdir(self.workdir)

    with self.context.new_workunit(name='jar-create', labels=[WorkUnit.MULTITOOL]):
      for target in self.context.targets(is_jvm_library):
        jar_name = jarname(target)
        jar_path = os.path.join(self.workdir, jar_name)
        with self.create_jar(target, jar_path) as jarfile:
          if self._jar_builder.add_target(jarfile, target):
            self.context.products.get('jars').add(target, self.workdir).append(jar_name)

  @contextmanager
  def create_jar(self, target, path):
    existing = self._jars.setdefault(path, target)
    if target != existing:
      raise TaskError('Duplicate name: target %s tried to write %s already mapped to target %s' % (
        target, path, existing
      ))
    self._jars[path] = target
    with self.open_jar(path, overwrite=True, compressed=self.compressed) as jar:
      yield jar
