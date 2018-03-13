# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

import requests

from pants.cache.artifact import ArtifactError
from pants.cache.artifact_cache import NonfatalArtifactCacheError, UnreadableArtifact
from pants.goal.artifact_cache_stats import ArtifactCacheStats
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest


class ArtifactCacheStatsTest(BaseTest):
  TEST_CACHE_NAME_1 = 'ZincCompile'
  TEST_CACHE_NAME_2 = 'Checkstyle_test_checkstyle'
  TEST_LOCAL_ERROR = UnreadableArtifact('foo', ArtifactError('CRC check failed'))
  TEST_REMOTE_ERROR = UnreadableArtifact(
    'bar',
    NonfatalArtifactCacheError(requests.exceptions.ConnectionError('Read time out'))
  )
  TEST_SPEC_A = 'src/scala/a'
  TEST_SPEC_B = 'src/scala/b'
  TEST_SPEC_C = 'src/java/c'

  def setUp(self):
    super(ArtifactCacheStatsTest, self).setUp()

    self.target_a = self.make_target(spec=self.TEST_SPEC_A)
    self.target_b = self.make_target(spec=self.TEST_SPEC_B)
    self.target_c = self.make_target(spec=self.TEST_SPEC_C)

  def test_add_hits(self):
    expected_stats = [
      {
        'cache_name': self.TEST_CACHE_NAME_2,
        'num_hits': 0,
        'num_misses': 1,
        'hits': [],
        'misses': [(self.TEST_SPEC_A, str(self.TEST_LOCAL_ERROR.err))]
      },
      {
        'cache_name': self.TEST_CACHE_NAME_1,
        'num_hits': 1,
        'num_misses': 1,
        'hits': [(self.TEST_SPEC_B, '')],
        'misses': [(self.TEST_SPEC_C, str(self.TEST_REMOTE_ERROR.err))]
      },
    ]

    expected_hit_or_miss_files = {
      '{}.misses'.format(self.TEST_CACHE_NAME_2):
        '{} {}\n'.format(self.TEST_SPEC_A, str(self.TEST_LOCAL_ERROR.err)),
      '{}.hits'.format(self.TEST_CACHE_NAME_1):
        '{}\n'.format(self.TEST_SPEC_B),
      '{}.misses'.format(self.TEST_CACHE_NAME_1):
        '{} {}\n'.format(self.TEST_SPEC_C, str(self.TEST_REMOTE_ERROR.err)),
    }

    with self.mock_artifact_cache_stats(expected_stats,
                                        expected_hit_or_miss_files=expected_hit_or_miss_files)\
        as artifact_cache_stats:
      artifact_cache_stats.add_hits(self.TEST_CACHE_NAME_1, [self.target_b])
      artifact_cache_stats.add_misses(self.TEST_CACHE_NAME_1, [self.target_c],
                                      [self.TEST_REMOTE_ERROR])
      artifact_cache_stats.add_misses(self.TEST_CACHE_NAME_2, [self.target_a],
                                      [self.TEST_LOCAL_ERROR])

  @contextmanager
  def mock_artifact_cache_stats(self,
                                expected_stats,
                                expected_hit_or_miss_files=None):
    with temporary_dir() as tmp_dir:
      artifact_cache_stats = ArtifactCacheStats(tmp_dir)
      yield artifact_cache_stats
      self.assertEquals(expected_stats, artifact_cache_stats.get_all())

      self.assertEquals(sorted(list(expected_hit_or_miss_files.keys())),
                        sorted(os.listdir(tmp_dir)))
      for hit_or_miss_file in expected_hit_or_miss_files.keys():
        with open(os.path.join(tmp_dir, hit_or_miss_file)) as hit_or_miss_saved:
          self.assertEquals(expected_hit_or_miss_files[hit_or_miss_file], hit_or_miss_saved.read())
