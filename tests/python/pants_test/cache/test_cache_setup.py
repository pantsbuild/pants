# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from mock import Mock

from pants.cache.cache_setup import (CacheFactory, CacheSetup, CacheSpec, CacheSpecFormatError,
                                     EmptyCacheSpecError, InvalidCacheSpecError,
                                     LocalCacheSpecRequiredError, RemoteCacheSpecRequiredError,
                                     TooManyCacheSpecsError)
from pants.cache.local_artifact_cache import LocalArtifactCache
from pants.cache.resolver import Resolver
from pants.cache.restful_artifact_cache import RESTfulArtifactCache
from pants.subsystem.subsystem import Subsystem
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest
from pants_test.testutils.mock_logger import MockLogger


class DummyContext(object):
  log = MockLogger()


class DummyTask(Task):
  options_scope = 'dummy'

  context = DummyContext()

  @classmethod
  def subsystem_dependencies(cls):
    return super(DummyTask, cls).subsystem_dependencies() + (CacheSetup, )


class MockPinger(object):

  def __init__(self, hosts_to_times):
    self._hosts_to_times = hosts_to_times

  # Returns a fake ping time such that the last host is always the 'fastest'.
  def pings(self, hosts):
    return map(lambda host: (host, self._hosts_to_times.get(host, 9999)), hosts)


class TestCacheSetup(BaseTest):

  TEST_RESOLVED_FROM = 'http://test-resolver'
  LOCAL_URI = '/a/local/path'
  INVALID_LOCAL_URI = '../not_a_valid_local_cache'
  REMOTE_URI_1 = 'http://host1'
  REMOTE_URI_2 = 'https://host2:666'
  REMOTE_URI_3 = 'http://host3'
  EMPTY_URI = 'http://localhost:9999'

  CACHE_SPEC_LOCAL_ONLY = CacheSpec(local=LOCAL_URI, remote=None)
  CACHE_SPEC_REMOTE_ONLY = CacheSpec(local=None, remote=REMOTE_URI_1)
  CACHE_SPEC_LOCAL_REMOTE = CacheSpec(local=LOCAL_URI, remote=REMOTE_URI_1)
  CACHE_SPEC_RESOLVE_ONLY = CacheSpec(local=None, remote=TEST_RESOLVED_FROM)
  CACHE_SPEC_LOCAL_RESOLVE = CacheSpec(local=LOCAL_URI, remote=TEST_RESOLVED_FROM)

  def setUp(self):
    super(TestCacheSetup, self).setUp()

    self.resolver = Mock(spec=Resolver)
    self.resolver.resolve = Mock(return_value=[self.REMOTE_URI_1, self.REMOTE_URI_2])
    self.log = MockLogger()
    self.pinger = MockPinger({'host1': 5, 'host2:666': 3, 'host3': 7})
    options = Mock()
    options.pinger_timeout = .5
    options.pinger_tries = 2
    options.read_from = [self.EMPTY_URI]
    options.write_to = [self.EMPTY_URI]
    options.compression_level = 1
    self.cache_factory = CacheFactory(options=options, log=MockLogger(),
                                 stable_name='test', resolver=self.resolver)

  def test_sanitize_cache_spec(self):
    self.assertEquals(self.CACHE_SPEC_LOCAL_ONLY,
                      self.cache_factory._sanitize_cache_spec([self.LOCAL_URI]))

    self.assertEquals(self.CACHE_SPEC_REMOTE_ONLY,
                      self.cache_factory._sanitize_cache_spec([self.REMOTE_URI_1]))

    # (local, remote) and (remote, local) are equivalent as long as they are valid
    self.assertEquals(self.CACHE_SPEC_LOCAL_REMOTE,
                      self.cache_factory._sanitize_cache_spec([self.LOCAL_URI, self.REMOTE_URI_1]))
    self.assertEquals(self.CACHE_SPEC_LOCAL_REMOTE,
                      self.cache_factory._sanitize_cache_spec([self.REMOTE_URI_1, self.LOCAL_URI]))

    with self.assertRaises(InvalidCacheSpecError):
      self.cache_factory._sanitize_cache_spec('not a list')

    with self.assertRaises(EmptyCacheSpecError):
      self.cache_factory._sanitize_cache_spec([])

    with self.assertRaises(CacheSpecFormatError):
      self.cache_factory._sanitize_cache_spec([self.INVALID_LOCAL_URI])
    with self.assertRaises(CacheSpecFormatError):
      self.cache_factory._sanitize_cache_spec(['ftp://not_a_valid_remote_cache'])

    with self.assertRaises(LocalCacheSpecRequiredError):
      self.cache_factory._sanitize_cache_spec([self.INVALID_LOCAL_URI, self.REMOTE_URI_1])
    with self.assertRaises(LocalCacheSpecRequiredError):
      self.cache_factory._sanitize_cache_spec([self.REMOTE_URI_1, self.REMOTE_URI_2])
    with self.assertRaises(RemoteCacheSpecRequiredError):
      self.cache_factory._sanitize_cache_spec([self.LOCAL_URI, self.INVALID_LOCAL_URI])

    with self.assertRaises(TooManyCacheSpecsError):
      self.cache_factory._sanitize_cache_spec([self.LOCAL_URI,
                                               self.REMOTE_URI_1, self.REMOTE_URI_2])

  def test_resolve(self):
    self.assertEquals(CacheSpec(local=None,
                                remote='{}|{}'.format(self.REMOTE_URI_1, self.REMOTE_URI_2)),
                      self.cache_factory._resolve(self.CACHE_SPEC_RESOLVE_ONLY))

    self.assertEquals(CacheSpec(local=self.LOCAL_URI,
                                remote='{}|{}'.format(self.REMOTE_URI_1, self.REMOTE_URI_2)),
                      self.cache_factory._resolve(self.CACHE_SPEC_LOCAL_RESOLVE))

    self.resolver.resolve.side_effect = Resolver.ResolverError()
    # still have local cache if resolver fails
    self.assertEquals(CacheSpec(local=self.LOCAL_URI, remote=None),
                      self.cache_factory._resolve(self.CACHE_SPEC_LOCAL_RESOLVE))
    # no cache created if resolver fails and no local cache
    self.assertFalse(self.cache_factory._resolve(self.CACHE_SPEC_RESOLVE_ONLY))

  def test_noop_resolve(self):
    self.resolver.resolve = Mock(return_value=[])

    self.assertEquals(self.CACHE_SPEC_LOCAL_ONLY,
                      self.cache_factory._resolve(self.CACHE_SPEC_LOCAL_ONLY))
    self.assertEquals(self.CACHE_SPEC_RESOLVE_ONLY,
                      self.cache_factory._resolve(self.CACHE_SPEC_RESOLVE_ONLY))
    self.assertEquals(self.CACHE_SPEC_LOCAL_RESOLVE,
                      self.cache_factory._resolve(self.CACHE_SPEC_LOCAL_RESOLVE))

  def test_cache_spec_parsing(self):
    def mk_cache(spec, resolver=None):
      Subsystem.reset()
      self.set_options_for_scope(CacheSetup.subscope(DummyTask.options_scope),
                                 read_from=spec, compression=1)
      self.context(for_task_types=[DummyTask])  # Force option initialization.
      cache_factory = CacheSetup.create_cache_factory_for_task(DummyTask,
                                                               pinger=self.pinger,
                                                               resolver=resolver)
      return cache_factory.get_read_cache()

    def check(expected_type, spec, resolver=None):
      cache = mk_cache(spec, resolver=resolver)
      self.assertIsInstance(cache, expected_type)
      self.assertEquals(cache.artifact_root, self.pants_workdir)

    with temporary_dir() as tmpdir:
      cachedir = os.path.join(tmpdir, 'cachedir')  # Must be a real path, so we can safe_mkdir it.
      check(LocalArtifactCache, [cachedir])
      check(RESTfulArtifactCache, ['http://localhost/bar'])
      check(RESTfulArtifactCache, ['https://localhost/bar'])
      check(RESTfulArtifactCache, [cachedir, 'http://localhost/bar'])
      check(RESTfulArtifactCache, [cachedir, 'http://localhost/bar'], resolver=self.resolver)

      with self.assertRaises(CacheSpecFormatError):
        mk_cache(['foo'])

      with self.assertRaises(CacheSpecFormatError):
        mk_cache(['../foo'])

      with self.assertRaises(LocalCacheSpecRequiredError):
        mk_cache(['https://localhost/foo', 'http://localhost/bar'])

      with self.assertRaises(RemoteCacheSpecRequiredError):
        mk_cache([tmpdir, '/bar'])

      with self.assertRaises(TooManyCacheSpecsError):
        mk_cache([tmpdir, self.REMOTE_URI_1, self.REMOTE_URI_2])

  def test_read_cache_available(self):
    self.assertEquals(None, self.cache_factory.read_cache_available())

  def test_write_cache_available(self):
    self.assertEquals(None, self.cache_factory.write_cache_available())
