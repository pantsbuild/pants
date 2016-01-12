# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.invalidation.build_invalidator import CacheKey
from pants.invalidation.cache_manager import VersionedTarget
from pants.task.recursive_version import RecursiveVersion
from pants.task.task import TaskBase
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest


class VersionedTaskCacheTester(TaskBase):
  options_scope = 'versioned-cache-test'
  pass


class TaskV1(VersionedTaskCacheTester):
  version = RecursiveVersion(1)


class TaskV2(VersionedTaskCacheTester):
  version = RecursiveVersion(2)


class VersionedClassTests(BaseTest):
  def test_versioned_cache(self):
    """Verify that cache for different versions of the same Task
    are stored in different locations.
    """
    context = self.context(options={
      'cache.versioned-cache-test': {
        'pinger_timeout': 1,
        'pinger_tries': 1,
        'resolver': 'rest',
      }
    })
    test_address = Address('//:testtarget', 'test_target')
    cache_key = CacheKey(id='test', hash='testhash', num_chunking_units=1)
    target = Target('test_target', test_address, None)

    with temporary_dir() as workdir:
      cache_dir = os.path.join(workdir, 'cache_test')
      #Create a task instance
      task1 = TaskV1(context, workdir)
      task2 = TaskV2(context, workdir)

      #Fetch the cacheManager to use in VTS
      cm_1 = task1.create_cache_manager(False)
      cm_2 = task2.create_cache_manager(False)

      #Create versionedTarget and pass it cm1.
      vt1 = VersionedTarget(cm_1, target, cache_key)
      vt1.create_results_dir(cache_dir, True)

      #Create versionedTarget and pass it cm1.
      vt2 = VersionedTarget(cm_2, target, cache_key)
      vt2.create_results_dir(cache_dir, True)

      cached_dirs = os.listdir(os.path.join(workdir,cache_dir))
      self.assertEquals(len(cached_dirs), 2)
