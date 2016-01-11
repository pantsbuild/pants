# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import TaskBase


class VersionedTaskCacheTester(TaskBase):
  pass

class TaskV1(VersionedTaskCacheTester):
  version = RecursiveVersion(1)

class TaskV2(VersionedTaskCacheTester):
  version = RecursiveVersion(2)

def test_versioned_VTS_cache():
  #Create a task instance
  #Fetch the cacheManager to use in VTS

  #Call VTS. with cachemanager tmpdir root, and version
  #check that directory is correct
  pass
