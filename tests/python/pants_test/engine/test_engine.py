# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import closing, contextmanager

from concurrent.futures import Future
from mock import call, create_autospec

from pants.build_graph.address import Address
from pants.engine.engine import (LocalMultiprocessEngine, LocalSerialEngine, SerializationError,
                                 ThreadHybridEngine)
from pants.engine.nodes import FilesystemNode, Return, SelectNode
from pants.engine.scheduler import Promise
from pants.engine.storage import Cache, Storage
from pants_test.engine.examples.planners import Classpath, setup_json_scheduler


class EngineTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler = setup_json_scheduler(build_root)

    self.java = Address.parse('src/java/codegen/simple')

  def request(self, goals, *addresses):
    return self.scheduler.build_request(goals=goals,
                                        subjects=addresses)

  def assert_engine(self, engine):
    result = engine.execute(self.request(['compile'], self.java))
    self.assertEqual({SelectNode(self.java, Classpath, None, None):
                      Return(Classpath(creator='javac'))},
                     result.root_products)
    self.assertIsNone(result.error)

  @contextmanager
  def multiprocessing_engine(self, pool_size=None):
    storage = Storage.create(debug=True, in_memory=False)
    cache = Cache.create(storage=storage)
    with closing(LocalMultiprocessEngine(self.scheduler, storage, cache,
                                         pool_size=pool_size, debug=True)) as e:
      e.start()
      yield e

  @contextmanager
  def hybrid_engine(self, pool_size=None):
    async_nodes = (FilesystemNode,)
    storage = Storage.create(debug=True, in_memory=False)
    cache = Cache.create(storage=storage)
    with closing(ThreadHybridEngine(self.scheduler, storage,
                                    threaded_node_types=async_nodes, cache=cache,
                                    pool_size=pool_size, debug=True)) as e:
      e.start()
      yield e

  def test_serial_engine_simple(self):
    with closing(LocalSerialEngine(self.scheduler)) as engine:
      self.assert_engine(engine)

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3510')
  def test_multiprocess_engine_multi(self):
    with self.multiprocessing_engine() as engine:
      self.assert_engine(engine)

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3510')
  def test_multiprocess_engine_single(self):
    with self.multiprocessing_engine(pool_size=1) as engine:
      self.assert_engine(engine)

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3510')
  def test_multiprocess_unpickleable(self):
    build_request = self.request(['unpickleable'], self.java)

    with self.multiprocessing_engine() as engine:
      with self.assertRaises(SerializationError):
        engine.execute(build_request)

  def test_hybrid_engine_multi(self):
    with self.hybrid_engine(pool_size=2) as engine:
      self.assert_engine(engine)

  def test_hybrid_engine_single(self):
    with self.hybrid_engine(pool_size=2) as engine:
      self.assert_engine(engine)

  def test_second_pending_future(self):
    """Validate we handle cache/step correctly

    Verify we don't raise a key error when 1 Node finishes cache/step
    before another Node.  Also verify that success is only called once
    for each Node.
    """
    result_cache = create_autospec(Future)
    result_cache2 = create_autospec(Future)
    result_step = create_autospec(Future)
    result_cache2.result.return_value = (2, 'cache 2')
    result_cache.result.return_value = (1, 'cache 1')
    result_step.result.return_value = (1, 'step 1')
    promise = create_autospec(Promise)

    in_flight = {1: promise, 2: promise}
    with self.hybrid_engine(pool_size=2) as engine:
      engine._processed_queue.put(result_cache)
      engine._processed_queue.put(result_step)
      engine._processed_queue.put(result_cache2)
      engine._await_one(in_flight)
      engine._await_one(in_flight)

      promise.success.assert_has_calls([call('cache 1'), call('cache 2')])

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3510')
  def test_rerun_with_cache(self):
    with self.multiprocessing_engine() as engine:
      self.assert_engine(engine)

      cache_stats = engine.cache_stats()
      # First run all misses.
      self.assertTrue(cache_stats.hits == 0)

      # Save counts for the first run to prepare for another run.
      max_steps, misses, total = self.scheduler._step_id, cache_stats.misses, cache_stats.total

      self.scheduler.product_graph.invalidate()
      self.assert_engine(engine)

      # Second run executes same number of steps, and are all cache hits, no more misses.
      self.assertEquals(max_steps * 2, self.scheduler._step_id)
      self.assertEquals(total * 2, cache_stats.total)
      self.assertEquals(misses, cache_stats.misses)
      self.assertTrue(cache_stats.hits > 0)

      # Ensure we cache no more than what can be cached.
      for request, result in engine._cache.items():
        self.assertTrue(request[0].is_cacheable)
