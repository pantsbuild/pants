# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.cache.cache_setup import CacheSetup
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.dirutil import safe_rmtree


class Invalidator(Task):
  """Invalidate the entire build."""

  def execute(self):
    build_invalidator_dir = os.path.join(self.get_options().pants_workdir, 'build_invalidator')
    safe_rmtree(build_invalidator_dir)


class Cleaner(Task):
  """Clean all current build products."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(Cleaner, cls).subsystem_dependencies() + (
      CacheSetup.scoped(cls), IvySubsystem.scoped(cls))

  @classmethod
  def task_subsystems(cls):
    return super(Cleaner, cls).task_subsystems() + (IvySubsystem,)

  @classmethod
  def register_options(cls, register):
    super(Cleaner, cls).register_options(register)
    register('--skip-ivy', action='store_true', default=True,
             help='Skip .ivy directory')
    register('--skip-buildcache', action='store_true', default=True,
             help='Skip .buildcache directory')
    register('--skip-pex', action='store_true', default=True,
             help='Skip .pex directory')

  def execute(self):
    print()

    options = self.get_options()
    cache = CacheSetup.scoped_instance(self)
    cache_options = cache.get_options()

    ivy = IvySubsystem.scoped_instance(self)
    ivy_options = ivy.get_options()

    safe_rmtree(self.get_options().pants_workdir)
    if not options.skip_buildcache and cache_options.read_from:
      for dir in cache_options.read_from:
        print('Removing cache [read] dir: {}'.format(dir))
        safe_rmtree(dir)

    if not options.skip_buildcache and cache_options.write_to:
      for dir in cache_options.write_to:
        print('Removing cache [read] dir: {}'.format(dir))
        safe_rmtree(dir)

    if not self.get_options().skip_pex:
      pex_path = os.path.join(options.pants_workdir, '.pex')
      print('Removing .pex dir: {}'.format(pex_path))
      safe_rmtree(pex_path)

    if not options.skip_ivy:
      print('Removing Ivy cache dir: {}'.format(ivy_options.cache_dir))
      safe_rmtree(ivy_options.cache_dir)
