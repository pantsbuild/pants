# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import math

import mox

from pants.base.hash_utils import Sharder, hash_all, hash_file
from pants.util.contextutil import temporary_file


class TestHashUtils(mox.MoxTestBase):

  def setUp(self):
    super(TestHashUtils, self).setUp()
    self.digest = self.mox.CreateMockAnything()

  def test_hash_all(self):
    self.digest.update('jake')
    self.digest.update('jones')
    self.digest.hexdigest().AndReturn('42')
    self.mox.ReplayAll()

    self.assertEqual('42', hash_all(['jake', 'jones'], digest=self.digest))

  def test_hash_file(self):
    self.digest.update('jake jones')
    self.digest.hexdigest().AndReturn('1137')
    self.mox.ReplayAll()

    with temporary_file() as fd:
      fd.write('jake jones')
      fd.close()

      self.assertEqual('1137', hash_file(fd.name, digest=self.digest))

  def test_compute_shard(self):
    # Spot-check a couple of values, to make sure compute_shard doesn't do something
    # completely degenerate.
    self.assertEqual(31, Sharder.compute_shard('', 42))
    self.assertEqual(35, Sharder.compute_shard('foo', 42))
    self.assertEqual(5, Sharder.compute_shard('bar', 42))

  def test_compute_shard_distribution(self):
    # Check that shard distribution isn't obviously broken.
    nshards = 7
    mean_samples_per_shard = 10000
    nsamples = nshards * mean_samples_per_shard

    distribution = [0] * nshards
    for n in range(0, nsamples):
      shard = Sharder.compute_shard(str(n), nshards)
      distribution[shard] += 1

    variance = sum([(x - mean_samples_per_shard) ** 2 for x in distribution]) / nshards
    stddev = math.sqrt(variance)

    # We arbitrarily assert that a stddev of less than 1% of the mean is good enough
    # for sanity-checking purposes.
    self.assertLess(stddev, 100)

  def test_sharder(self):
    def check(spec, expected_shard, expected_nshards):
      sharder = Sharder(spec)
      self.assertEquals(expected_shard, sharder.shard)
      self.assertEquals(expected_nshards, sharder.nshards)

    def check_bad_spec(spec):
      self.assertRaises(Sharder.InvalidShardSpec, lambda: Sharder(spec))

    check('0/1', 0, 1)
    check('0/2', 0, 2)
    check('1/2', 1, 2)
    check('0/100', 0, 100)
    check('99/100', 99, 100)

    check_bad_spec('0/0')
    check_bad_spec('-1/0')
    check_bad_spec('0/-1')
    check_bad_spec('1/1')
    check_bad_spec('2/1')
    check_bad_spec('100/100')
    check_bad_spec('1/2/3')
    check_bad_spec('/1')
    check_bad_spec('1/')
    check_bad_spec('/')
    check_bad_spec('foo/1')
    check_bad_spec('1/foo')
