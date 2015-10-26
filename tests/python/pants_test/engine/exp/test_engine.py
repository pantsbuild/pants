# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import closing

from pants.build_graph.address import Address
from pants.engine.exp.engine import LocalMultiprocessEngine, LocalSerialEngine
from pants.engine.exp.examples.planners import Classpath, Javac, setup_json_scheduler
from pants.engine.exp.scheduler import BuildRequest, Promise


class EngineTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.graph, self.scheduler = setup_json_scheduler(build_root)

    self.java = self.graph.resolve(Address.parse('src/java/codegen/simple'))

  def assert_engine(self, engine):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    result = engine.execute(build_request)
    self.assertEqual({Promise(Classpath, self.java): Javac.fake_product()},
                     result.root_products)

  def test_serial_engine(self):
    engine = LocalSerialEngine(self.scheduler)
    self.assert_engine(engine)

  def test_multiprocess_engine(self):
    with closing(LocalMultiprocessEngine(self.scheduler)) as engine:
      self.assert_engine(engine)
