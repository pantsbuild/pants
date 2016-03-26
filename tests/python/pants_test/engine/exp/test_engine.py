# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import closing, contextmanager

from pants.build_graph.address import Address
from pants.engine.exp.engine import (LocalMultiprocessEngine, LocalSerialEngine, SerializationError,
                                     StorageIO)
from pants.engine.exp.examples.planners import Classpath, setup_json_scheduler
from pants.engine.exp.nodes import Return, SelectNode
from pants.engine.exp.scheduler import StepRequest, StepResult
from pants.engine.exp.storage import Cache, Key, Storage


class EngineTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler, self.storage = setup_json_scheduler(build_root, debug=True)
    self.cache = Cache.create(Storage.create())

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
    with self.multiprocessing_engine() as engine:
      self.assert_engine(engine)

      cache_stats = engine._cache.get_stats()
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


class StorageIOTest(unittest.TestCase):
  class SomeException(Exception): pass

  def setUp(self):
    self.storage_io = StorageIO(Storage.create(in_memory=True))
    self.result = StepResult(state='something')
    self.error = self.SomeException('error')
    self.request = StepRequest(step_id=123, node='some node',
                               dependencies={'some dep': 'some state',
                                             'another dep': 'another state'},
                               project_tree='some project tree')

  def test_key_for_request(self):
    with closing(self.storage_io):
      keyed_request = self.storage_io.key_for_request(self.request)
      for dep, dep_state in keyed_request.dependencies.items():
        self.assertEquals(Key, type(dep))
        self.assertEquals(Key, type(dep_state))
      self.assertIs(self.request.node, keyed_request.node)
      self.assertIs(self.request.project_tree, keyed_request.project_tree)

  def test_resolve_request(self):
    with closing(self.storage_io):
      keyed_request = self.storage_io.key_for_request(self.request)
      resolved_request = self.storage_io.resolve_request(keyed_request)
      self.assertEquals(self.request, resolved_request)
      self.assertIsNot(self.request, resolved_request)

      # resolve the resolved request will produce a different but equal request.
      resolved_again_request = self.storage_io.resolve_request(resolved_request)
      self.assertEquals(resolved_request, resolved_again_request)
      self.assertIsNot(resolved_request, resolved_again_request)

  def test_key_for_result(self):
    with closing(self.storage_io):
      keyed_result = self.storage_io.key_for_result(self.result)
      self.assertEquals(Key, type(keyed_result.state))

  def test_resolve_result(self):
    with closing(self.storage_io):
      keyed_result = self.storage_io.key_for_result(self.result)
      resolved_result = self.storage_io.resolve_result(keyed_result)
      self.assertEquals(self.result, resolved_result)
      self.assertIsNot(self.result, resolved_result)

      # resolve the resolved result will produce a different but equal result.
      resolved_again_result = self.storage_io.resolve_result(resolved_result)
      self.assertEquals(resolved_result, resolved_again_result)
      self.assertIsNot(resolved_result, resolved_again_result)

  def test_resolve_result_not_step_result(self):
    """Verify the same result is returned if result is not StepResult."""
    with closing(self.storage_io):
      resolved_result = self.storage_io.resolve_result(self.error)
      self.assertIs(self.error, resolved_result)
