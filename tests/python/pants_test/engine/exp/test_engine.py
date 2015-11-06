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
from pants.engine.exp.examples.planners import (ApacheThriftError, Classpath, Javac, Sources,
                                                setup_json_scheduler)
from pants.engine.exp.scheduler import BuildRequest, Promise


class EngineTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.graph, self.scheduler = setup_json_scheduler(build_root)

    def resolve(spec):
      return self.graph.resolve(Address.parse(spec))

    self.java = resolve('src/java/codegen/simple')
    self.java_fail_slow = resolve('src/java/codegen/selector:failing')
    self.failing_thrift = resolve('src/thrift/codegen/selector:selector@failing')

  def assert_engine(self, engine):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    result = engine.execute(build_request)
    self.assertEqual({Promise(Classpath, self.java): Javac.fake_product()},
                     result.root_products)
    self.assertIsNone(result.error)

  @contextmanager
  def multiprocessing_engine(self, pool_size=None):
    with closing(LocalMultiprocessEngine(self.scheduler, pool_size=pool_size, debug=True)) as e:
      yield e

  def test_serial_engine(self):
    engine = LocalSerialEngine(self.scheduler)
    self.assert_engine(engine)

  def test_multiprocess_engine(self):
    with self.multiprocessing_engine() as engine:
      self.assert_engine(engine)

  def test_multiprocess_engine_single_process(self):
    with self.multiprocessing_engine(pool_size=1) as engine:
      self.assert_engine(engine)

  def assert_engine_fail_slow(self, engine):
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.java.address, self.java_fail_slow.address])
    result = engine.execute(build_request, fail_slow=True)
    self.assertEqual({Promise(Classpath, self.java): Javac.fake_product()},
                     result.root_products)

    self.assertIsInstance(result.error, Engine.PartialFailureError)
    self.assertEqual(1, len(result.error.failed_to_produce))
    failed_promise = Promise(Classpath, self.java_fail_slow)
    failed_to_produce = result.error.failed_to_produce[failed_promise]
    failing_configuration = self.failing_thrift.select_configuration('failing')
    self.assertEqual([Promise(Sources.of('.java'), self.failing_thrift, failing_configuration),
                      Promise(Classpath, self.failing_thrift, failing_configuration),
                      Promise(Classpath, self.java_fail_slow)],
                     [ftp.promise for ftp in failed_to_produce.walk(postorder=True)])
    errors = [ftp.error for ftp in failed_to_produce.walk(postorder=True)]
    self.assertEqual(3, len(errors))
    root_error = errors[0]
    self.assertIsInstance(root_error, ApacheThriftError)
    self.assertEqual([None, None], errors[1:])

  def test_serial_engine_fail_slow(self):
    engine = LocalSerialEngine(self.scheduler)
    self.assert_engine_fail_slow(engine)

  def test_multiprocess_engine_fail_slow(self):
    with self.multiprocessing_engine() as engine:
      self.assert_engine_fail_slow(engine)

  def test_multiprocess_engine_fail_slow_single_process(self):
    with self.multiprocessing_engine(pool_size=1) as engine:
      self.assert_engine_fail_slow(engine)

  def test_multiprocess_unpicklable_inputs(self):
    build_request = BuildRequest(goals=['unpickleable_inputs'],
                                 addressable_roots=[self.java.address])

    with self.multiprocessing_engine() as engine:
      with self.assertRaises(SerializationError):
        engine.execute(build_request)

  def test_multiprocess_unpicklable_outputs(self):
    build_request = BuildRequest(goals=['unpickleable_result'],
                                 addressable_roots=[self.java.address])

    with self.multiprocessing_engine() as engine:
      with self.assertRaises(SerializationError):
        engine.execute(build_request)
