# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestIndexJavaIntegration(PantsRunIntegrationTest):
  def test_index_simple_java_code(self):
    # Very simple test that we can run the extractor and indexer on some
    # fairly trivial code without crashing, and that we produce something.
    args = ['kythe', 'examples/src/java/org/pantsbuild/example/hello::']
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      for tgt in ['examples.src.java.org.pantsbuild.example.hello.greet.greet',
                  'examples.src.java.org.pantsbuild.example.hello.main.main-bin',
                  'examples.src.java.org.pantsbuild.example.hello.simple.simple']:
        kindex_glob = os.path.join(workdir,
                                   'kythe/extract/current/{}/current/*.kindex'.format(tgt))
        kindex_files = glob.glob(kindex_glob)
        self.assertEquals(1, len(kindex_files))
        kindex_file = kindex_files[0]
        self.assertTrue(os.path.isfile(kindex_file))
        self.assertGreater(os.path.getsize(kindex_file), 200)  # Make sure it's not trivial.

        entries_path = os.path.join(workdir,
                                    'kythe/index/current/{}/current/index.entries'.format(tgt))
        self.assertTrue(os.path.isfile(entries_path))
        self.assertGreater(os.path.getsize(entries_path), 1000)  # Make sure it's not trivial.
