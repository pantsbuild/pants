# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import multiprocessing
import os

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.exceptions import TaskError
from pants.base.execution_graph import ExecutionFailure, ExecutionGraph, Job
from pants.base.worker_pool import WorkerPool
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
    register('--compressed', default=True, action='store_true', help='Create compressed jars.')
    register('--jar-worker-count', default=multiprocessing.cpu_count(), action='store', type=int,
             help='Number of workers (threads) to use for jar creation.')

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
    self.worker_count = self.get_options().jar_worker_count
    self._jars = {}

  def _construct_jobs(self, jar_targets):
    """Job object generator for parallel jar-create tasks."""
    def jar_target(target, jar_name, jar_path):
      def work():
        with self.open_jar(jar_path, overwrite=True, compressed=self.compressed) as jar_file:
          with self.create_jar_builder(jar_file) as jar_builder:
            if target in jar_builder.add_target(target):
              self.context.products.get('jars').add(target, self.workdir).append(jar_name)
      return work

    for target, jar_name, jar_path in jar_targets:
      yield Job(key=target.address.spec,
                fn=jar_target(target, jar_name, jar_path),
                dependencies=[])

  def _prepare_jar_target(self, target):
    """Crafts an input tuple for a given target and checks for path collisions."""
    jar_name = jarname(target)
    jar_path = os.path.join(self.workdir, jar_name)

    existing = self._jars.get(jar_path, target)
    if existing != target:
      raise TaskError('Duplicate name: target {} tried to write {} already mapped to target {}'
                      .format(target, jar_path, existing))
    self._jars[jar_path] = target
    return (target, jar_name, jar_path)

  def execute(self):
    safe_mkdir(self.workdir)

    with self.context.new_workunit(name='jar-create', labels=[WorkUnit.MULTITOOL]) as workunit:
      jar_targets = [self._prepare_jar_target(t) for t in self.context.targets(is_jvm_library)]

      if not jar_targets:
        return

      jobs = self._construct_jobs(jar_targets)

      self.context.log.debug(
        'Initializing jar-create WorkerPool, workers={}'.format(self.worker_count))

      with WorkerPool(workunit, self.context.run_tracker, self.worker_count) as worker_pool:
        exec_graph = ExecutionGraph(jobs)
        try:
          exec_graph.execute(worker_pool, self.context.log)
        except ExecutionFailure as e:
          raise TaskError('Jar creation failure: {}'.format(e))
