# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import closing, contextmanager

from pants.build_graph.address import Address
from pants.engine.exp.engine import LocalMultiprocessEngine, LocalSerialEngine, SerializationError
from pants.engine.exp.examples.planners import Classpath, setup_json_scheduler
from pants.engine.exp.nodes import Return, SelectNode
from pants.engine.exp.storage import Cache, Storage


class EngineTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler, self.storage = setup_json_scheduler(build_root, debug=True)
    self.cache = Cache.create(Storage.create(in_memory=True))

    self.java = Address.parse('src/java/codegen/simple')

  def key(self, subject):
    return self.storage.put(subject)

  def request(self, goals, *addresses):
    return self.scheduler.build_request(goals=goals,
                                        subject_keys=self.storage.puts(addresses))

  def assert_engine(self, engine):
    result = engine.execute(self.request(['compile'], self.java))
    self.assertEqual({SelectNode(self.key(self.java), Classpath, None, None):
                      self.key(Return(Classpath(creator='javac')))},
                     result.root_products)
    self.assertIsNone(result.error)

  @contextmanager
  def multiprocessing_engine(self, pool_size=None):
    with closing(LocalMultiprocessEngine(self.scheduler, self.storage, self.cache,
                                         pool_size=pool_size, debug=True)) as e:
      e.start()
      yield e

  def test_serial_engine_simple(self):
    engine = LocalSerialEngine(self.scheduler, self.storage, self.cache)
    self.assert_engine(engine)

  def test_multiprocess_engine_multi(self):
    with self.multiprocessing_engine() as engine:
      self.assert_engine(engine)

  def test_multiprocess_engine_single(self):
    with self.multiprocessing_engine(pool_size=1) as engine:
      self.assert_engine(engine)

  def test_multiprocess_unpickleable(self):
    build_request = self.request(['unpickleable'], self.java)

    with self.multiprocessing_engine() as engine:
      with self.assertRaises(SerializationError):
        engine.execute(build_request)

  def test_rerun_with_cache(self):
    engine = LocalSerialEngine(self.scheduler, self.storage, self.cache)
    self.assert_engine(engine)

    cache_stats = engine._cache.get_stats()
    max_steps, hits, misses = self.scheduler._step_id, cache_stats.hits, cache_stats.misses

    # First run most are cache misses.
    self.assertEquals(max_steps, cache_stats.total)

    self.scheduler.product_graph.clear()
    self.scheduler._step_id = 0
    self.assert_engine(engine)

    # Second run executes same number of steps, and are all cache hits.
    self.assertEquals(max_steps, self.scheduler._step_id)
    self.assertEquals(misses, cache_stats.misses)
    self.assertEquals(hits + max_steps, cache_stats.hits)
