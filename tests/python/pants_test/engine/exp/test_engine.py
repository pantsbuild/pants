# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import closing, contextmanager

from pants.build_graph.address import Address
from pants.engine.exp.engine import (Engine, LocalMultiprocessEngine, LocalSerialEngine,
                                     SerializationError)
from pants.engine.exp.examples.planners import (ApacheThriftError, Classpath, JavaSources,
                                                setup_json_scheduler)
from pants.engine.exp.scheduler import BuildRequest, Return, SelectNode


class EngineTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.graph, self.scheduler = setup_json_scheduler(build_root)

    def resolve(spec):
      return self.graph.resolve(Address.parse(spec))

    self.java = resolve('src/java/codegen/simple')

  def assert_engine(self, engine):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    result = engine.execute(build_request)
    self.assertEqual({SelectNode(self.java, Classpath, None): Return(Classpath(creator='javac'))},
                     result.root_products)
    self.assertIsNone(result.error)

  @contextmanager
  def multiprocessing_engine(self, pool_size=None):
    with closing(LocalMultiprocessEngine(self.scheduler, pool_size=pool_size, debug=True)) as e:
      yield e

  def test_serial_engine_simple(self):
    engine = LocalSerialEngine(self.scheduler)
    self.assert_engine(engine)

  def test_multiprocess_engine_multi(self):
    with self.multiprocessing_engine() as engine:
      self.assert_engine(engine)

  def test_multiprocess_engine_single(self):
    with self.multiprocessing_engine(pool_size=1) as engine:
      self.assert_engine(engine)

  def test_multiprocess_unpickleable(self):
    build_request = BuildRequest(goals=['unpickleable'],
                                 addressable_roots=[self.java.address])

    with self.multiprocessing_engine() as engine:
      with self.assertRaises(SerializationError):
        engine.execute(build_request)
