# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import shutil
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.goal.products import MultipleRootedProducts
from pants.option.options import Options
from pants.util.contextutil import open_zip
from pants.util.dirutil import relativize_path, safe_mkdir


class PrepareResourcesDirectory:
  def __init__(self, workdir, buildroot, context):
    self.workdir = workdir
    self.buildroot = buildroot
    self.context = context

  def compute_target_dir(self, resources_target):
    """Compute a directory under the task's work dir to hold its resources.
    :param resources_target: The Resources target.
    :return: the relativized directory path.
    """
    # Sources are all relative to their roots: relativize directories as well to
    # avoid breaking filesystem limits.
    return relativize_path(os.path.join(self.workdir, resources_target.id), self.buildroot)

  def prepare(self, resources_target):
    """Prepare the resources for the given target by copying the files to a resources directory.
    :param resources_target: The Resources target.
    """
    target_dir = os.path.join(self.buildroot, self.compute_target_dir(resources_target))
    self.context.log.debug(
      'Writing resources of target \'{}\' into dir \'{}\':'.format(resources_target.id, target_dir))
    safe_mkdir(target_dir, clean=True)
    for resource_file_from_source_root in resources_target.sources_relative_to_source_root():
      basedir = os.path.dirname(resource_file_from_source_root)
      destdir = os.path.join(target_dir, basedir)
      safe_mkdir(destdir)
      # TODO: Symlink instead?
      src = os.path.join(
        self.buildroot,
        resources_target.target_base,
        resource_file_from_source_root)
      dest = os.path.join(target_dir, resource_file_from_source_root)
      self.context.log.debug('  {}'.format(src))
      shutil.copy(src, dest)


class PrepareResourcesJar:
  def __init__(self, workdir, buildroot, use_jar, short_path, context):
    self.workdir = workdir
    self.buildroot = buildroot
    self.use_jar = use_jar
    self.short_path = short_path
    self.context = context

  def compute_target_jar(self, resources_target):
    """Compute a jar path in which the target's resources will be zipped in.
    :param resources_target: The Resources target.
    :return: the relativized jar path.
    """
    assert self.use_jar
    # If --short-path is specified, then we'll try to pick the shorter one between
    # the original target id based jar name and the sha1 digested jar name. Using sha1() instead
    # of hash() to avoid potential collision.
    jar_name = resources_target.id
    if self.short_path:
      sha = hashlib.sha1()
      sha.update(jar_name)
      hashed_jar_name = sha.hexdigest()
      jar_name = jar_name if len(jar_name) < len(hashed_jar_name) else hashed_jar_name
    jar_name += '.jar'
    return relativize_path(os.path.join(self.workdir, jar_name), self.buildroot)

  def prepare(self, resources_target):
    """Prepare the resources for the given target by creating a jar and zipping all the resources
      files into the jar.
    :param resources_target: The Resources target
    """
    target_jar = os.path.join(self.buildroot, self.compute_target_jar(resources_target))
    self.context.log.debug(
      'Writing resources of target \'{}\' into jar \'{}\':'.format(resources_target.id, target_jar))
    safe_mkdir(os.path.dirname(target_jar))
    with open_zip(target_jar, 'w') as jar:
      for resource_file_from_source_root in resources_target.sources_relative_to_source_root():
        self.context.log.debug('  {}'.format(resource_file_from_source_root))
        jar.write(
          os.path.join(self.buildroot,
                       resources_target.target_base,
                       resource_file_from_source_root),
          resource_file_from_source_root)


class PrepareResources(Task):

  @classmethod
  def register_options(cls, register):
    super(PrepareResources, cls).register_options(register)
    register('--confs', advanced=True, type=Options.list, default=['default'],
             help='Prepare resources for these Ivy confs.')
    register('--use-jar', advanced=True, action='store_true', default=False,
             help='Zip resources into a jar for class loader performance during test, run, or repl.'
                  ' Tests must be written without the assumption that resources are directly laying'
                  ' in the filesystem. If not, either disable this global option or turn use_jar'
                  ' off in the specific Resources target.')
    register('--short-path', advanced=True, action='store_true', default=True,
             help='Replace the target id in a resource jar file path with a unique '
                  'id to shorten the file path.')

  @classmethod
  def product_types(cls):
    return ['resources_by_target']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')
    # NOTE(Garrett Malmquist): This is a fake dependency to force resources to occur after jvm
    # compile. It solves some problems we've been having getting our annotation processors to
    # compile consistently due to extraneous resources polluting the classpath. Perhaps this could
    # be fixed more elegantly whenever we get a formal classpath object?
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(PrepareResources, self).__init__(*args, **kwargs)
    self.confs = self.get_options().confs
    self._buildroot = get_buildroot()
    self.use_jar = self.get_options().use_jar
    self.short_path = self.get_options().short_path
    self.prepare_resources_directory = PrepareResourcesDirectory(
      self.workdir, self._buildroot, self.context)
    self.prepare_resources_jar = PrepareResourcesJar(
      self.workdir, self._buildroot, self.use_jar, self.short_path, self.context)

  def execute(self):
    if self.context.products.is_required_data('resources_by_target'):
      self.context.products.safe_create_data('resources_by_target',
                                             lambda: defaultdict(MultipleRootedProducts))

    # NB: Ordering isn't relevant here, because it is applied during the dep walk to
    # consume from the compile_classpath.
    targets = self.context.targets()
    if len(targets) == 0:
      return
    def extract_resources(target):
      return target.resources if target.has_resources else ()
    all_resources_tgts = OrderedSet()
    for resources_tgts in map(extract_resources, targets):
      all_resources_tgts.update(resources_tgts)

    with self.invalidated(all_resources_tgts) as invalidation_check:
      invalid_targets = set()
      for vt in invalidation_check.invalid_vts:
        invalid_targets.update(vt.targets)

      for resources_tgt in invalid_targets:
        if self.use_jar and resources_tgt.use_jar:
          self.prepare_resources_jar.prepare(resources_tgt)
        else:
          self.prepare_resources_directory.prepare(resources_tgt)

      resources_by_target = self.context.products.get_data('resources_by_target')
      compile_classpath = self.context.products.get_data('compile_classpath')

      for resources_tgt in all_resources_tgts:
        if self.use_jar and resources_tgt.use_jar:
          resources_path = self.prepare_resources_jar.compute_target_jar(resources_tgt)
        else:
          resources_path = self.prepare_resources_directory.compute_target_dir(resources_tgt)
        for conf in self.confs:
          # TODO(John Sirois): Introduce the notion of RuntimeClasspath and populate that product
          # instead of mutating the compile_classpath.
          compile_classpath.add_for_target(resources_tgt, [(conf, resources_path)])
        if resources_by_target is not None:
          resources_by_target[resources_tgt].add_rel_paths(
            resources_path, resources_tgt.sources_relative_to_source_root())
