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
from pants_test.option.util.fakes import create_options
from pants_test.testutils.mock_logger import MockLogger


class DummyTask(Task):
  options_scope = 'dummy'
  _stable_name = 'test'

  @classmethod
  def subsystem_dependencies(cls):
    return super(DummyTask, cls).subsystem_dependencies() + (CacheSetup, )

  def execute(self): pass


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

  def create_task(self):
    return DummyTask(self.context(for_task_types=[DummyTask]),
                     self.pants_workdir)

  def setUp(self):
    super(TestCacheSetup, self).setUp()

    self.resolver = Mock(spec=Resolver)
    self.resolver.resolve = Mock(return_value=[self.REMOTE_URI_1, self.REMOTE_URI_2])
    self.log = MockLogger()
    self.pinger = MockPinger({'host1': 5, 'host2:666': 3, 'host3': 7})

  def cache_factory(self, **options):
    cache_options = {
      'pinger_timeout': .5,
      'pinger_tries': 2,
      'ignore': False,
      'read': False,
      'read_from': [self.EMPTY_URI],
      'write_to': [self.EMPTY_URI],
      'write': False,
      'compression_level': 1,
      'max_entries_per_target': 1,
      'write_permissions': None,
      'dereference_symlinks': True,
      # Usually read from global scope.
      'pants_workdir': self.pants_workdir
    }
    cache_options.update(**options)
    return CacheFactory(create_options(options={'test': cache_options}).for_scope('test'),
                        MockLogger(),
                        self.create_task(),
                        resolver=self.resolver)

  def test_sanitize_cache_spec(self):
    cache_factory = self.cache_factory()

    self.assertEquals(self.CACHE_SPEC_LOCAL_ONLY,
                      cache_factory._sanitize_cache_spec([self.LOCAL_URI]))

    self.assertEquals(self.CACHE_SPEC_REMOTE_ONLY,
                      cache_factory._sanitize_cache_spec([self.REMOTE_URI_1]))

    # (local, remote) and (remote, local) are equivalent as long as they are valid
    self.assertEquals(self.CACHE_SPEC_LOCAL_REMOTE,
                      cache_factory._sanitize_cache_spec([self.LOCAL_URI, self.REMOTE_URI_1]))
    self.assertEquals(self.CACHE_SPEC_LOCAL_REMOTE,
                      cache_factory._sanitize_cache_spec([self.REMOTE_URI_1, self.LOCAL_URI]))

    with self.assertRaises(InvalidCacheSpecError):
      cache_factory._sanitize_cache_spec('not a list')

    with self.assertRaises(EmptyCacheSpecError):
      cache_factory._sanitize_cache_spec([])

    with self.assertRaises(CacheSpecFormatError):
      cache_factory._sanitize_cache_spec([self.INVALID_LOCAL_URI])
    with self.assertRaises(CacheSpecFormatError):
      cache_factory._sanitize_cache_spec(['ftp://not_a_valid_remote_cache'])

    with self.assertRaises(LocalCacheSpecRequiredError):
      cache_factory._sanitize_cache_spec([self.INVALID_LOCAL_URI, self.REMOTE_URI_1])
    with self.assertRaises(LocalCacheSpecRequiredError):
      cache_factory._sanitize_cache_spec([self.REMOTE_URI_1, self.REMOTE_URI_2])
    with self.assertRaises(RemoteCacheSpecRequiredError):
      cache_factory._sanitize_cache_spec([self.LOCAL_URI, self.INVALID_LOCAL_URI])

    with self.assertRaises(TooManyCacheSpecsError):
      cache_factory._sanitize_cache_spec([self.LOCAL_URI,
                                    self.REMOTE_URI_1, self.REMOTE_URI_2])

  def test_resolve(self):
    cache_factory = self.cache_factory()

    self.assertEquals(CacheSpec(local=None,
                                remote='{}|{}'.format(self.REMOTE_URI_1, self.REMOTE_URI_2)),
                      cache_factory._resolve(self.CACHE_SPEC_RESOLVE_ONLY))

    self.assertEquals(CacheSpec(local=self.LOCAL_URI,
                                remote='{}|{}'.format(self.REMOTE_URI_1, self.REMOTE_URI_2)),
                      cache_factory._resolve(self.CACHE_SPEC_LOCAL_RESOLVE))

    self.resolver.resolve.side_effect = Resolver.ResolverError()
    # still have local cache if resolver fails
    self.assertEquals(CacheSpec(local=self.LOCAL_URI, remote=None),
                      cache_factory._resolve(self.CACHE_SPEC_LOCAL_RESOLVE))
    # no cache created if resolver fails and no local cache
    self.assertFalse(cache_factory._resolve(self.CACHE_SPEC_RESOLVE_ONLY))

  def test_noop_resolve(self):
    self.resolver.resolve = Mock(return_value=[])
    cache_factory = self.cache_factory()

    self.assertEquals(self.CACHE_SPEC_LOCAL_ONLY,
                      cache_factory._resolve(self.CACHE_SPEC_LOCAL_ONLY))
    self.assertEquals(self.CACHE_SPEC_RESOLVE_ONLY,
                      cache_factory._resolve(self.CACHE_SPEC_RESOLVE_ONLY))
    self.assertEquals(self.CACHE_SPEC_LOCAL_RESOLVE,
                      cache_factory._resolve(self.CACHE_SPEC_LOCAL_RESOLVE))

  def test_cache_spec_parsing(self):
    def mk_cache(spec, resolver=None):
      Subsystem.reset()
      self.set_options_for_scope(CacheSetup.subscope(DummyTask.options_scope),
                                 read_from=spec, compression=1)
      self.context(for_task_types=[DummyTask])  # Force option initialization.
      cache_factory = CacheSetup.create_cache_factory_for_task(
        self.create_task(),
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
    self.assertFalse(self.cache_factory(ignore=True, read=True, read_from=[self.EMPTY_URI])
                     .read_cache_available())
    self.assertFalse(self.cache_factory(ignore=False, read=False, read_from=[self.EMPTY_URI])
                     .read_cache_available())
    self.assertFalse(self.cache_factory(ignore=False, read=True, read_from=[])
                     .read_cache_available())
    self.assertIsNone(self.cache_factory(ignore=False, read=True, read_from=[self.EMPTY_URI])
                      .read_cache_available())

  def test_write_cache_available(self):
    self.assertFalse(self.cache_factory(ignore=True, write=True, write_to=[self.EMPTY_URI])
                     .write_cache_available())
    self.assertFalse(self.cache_factory(ignore=False, write=False, write_to=[self.EMPTY_URI])
                     .write_cache_available())
    self.assertFalse(self.cache_factory(ignore=False, write=True, write_to=[])
                     .write_cache_available())
    self.assertIsNone(self.cache_factory(ignore=False, write=True, write_to=[self.EMPTY_URI])
                      .write_cache_available())
