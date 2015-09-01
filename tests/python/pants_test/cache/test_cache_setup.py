# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.cache.cache_setup import (CacheFactory, CacheSetup, CacheSpecFormatError,
                                     LocalCacheSpecRequiredError, RemoteCacheSpecRequiredError)
from pants.cache.local_artifact_cache import LocalArtifactCache
from pants.cache.restful_artifact_cache import RESTfulArtifactCache
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest
from pants_test.testutils.mock_logger import MockLogger


class DummyContext(object):
  log = MockLogger()


class DummyTask(Task):
  options_scope = 'dummy'

  context = DummyContext()

  @classmethod
  def global_subsystems(cls):
    return super(DummyTask, cls).global_subsystems() + (CacheSetup, )


class MockPinger(object):

  def __init__(self, hosts_to_times):
    self._hosts_to_times = hosts_to_times

  # Returns a fake ping time such that the last host is always the 'fastest'.
  def pings(self, hosts):
    return map(lambda host: (host, self._hosts_to_times.get(host, 9999)), hosts)


class TestCacheSetup(BaseTest):

  def test_select_best_url(self):
    log = MockLogger()
    pinger = MockPinger({'host1': 5, 'host2:666': 3, 'host3': 7})
    cache_factory = CacheFactory(options={}, log=log, stable_name='test', pinger=pinger)
    spec = 'http://host1|https://host2:666/path/to|http://host3/path/'
    best = cache_factory.select_best_url(spec)
    self.assertEquals('https://host2:666/path/to', best)

  def test_cache_spec_parsing(self):
    def mk_cache(spec):
      Subsystem.reset()
      self.set_options_for_scope(CacheSetup.subscope(DummyTask.options_scope),
                                 read_from=spec, compression=1)
      self.context(for_task_types=[DummyTask])  # Force option initialization.
      cache_factory = CacheSetup.create_cache_factory_for_task(DummyTask)
      return cache_factory.get_read_cache()

    def check(expected_type, spec):
      cache = mk_cache(spec)
      self.assertIsInstance(cache, expected_type)
      self.assertEquals(cache.artifact_root, self.pants_workdir)

    with temporary_dir() as tmpdir:
      cachedir = os.path.join(tmpdir, 'cachedir')  # Must be a real path, so we can safe_mkdir it.
      check(LocalArtifactCache, cachedir)
      check(RESTfulArtifactCache, 'http://localhost/bar')
      check(RESTfulArtifactCache, 'https://localhost/bar')
      check(RESTfulArtifactCache, [cachedir, 'http://localhost/bar'])

      with self.assertRaises(CacheSpecFormatError):
        mk_cache('foo')

      with self.assertRaises(CacheSpecFormatError):
        mk_cache('../foo')

      with self.assertRaises(LocalCacheSpecRequiredError):
        mk_cache(['https://localhost/foo', 'http://localhost/bar'])

      with self.assertRaises(RemoteCacheSpecRequiredError):
        mk_cache([tmpdir, '/bar'])
