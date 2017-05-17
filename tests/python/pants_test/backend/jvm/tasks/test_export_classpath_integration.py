# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time

from pants.java.jar.manifest import Manifest
from pants.util.contextutil import open_zip
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExportClasspathIntegrationTest(PantsRunIntegrationTest):
  def test_export_manifest_jar(self):
    ctimes = []
    manifest_jar_path = "dist/export-classpath/manifest.jar"
    for _ in range(2):
      pants_run = self.run_pants(["export-classpath",
                                  "--manifest-jar-only",
                                  "examples/src/java/org/pantsbuild/example/hello/simple"])
      self.assert_success(pants_run)
      self.assertTrue(os.path.exists(manifest_jar_path))
      (mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime) = os.stat(manifest_jar_path)
      ctimes.append(ctime)
      # ctime is only accurate to second.
      time.sleep(1)

    self.assertTrue(ctimes[1] > ctimes[0], "{} is not overwritten.".format(manifest_jar_path))

  def test_export_classpath_file_with_excludes(self):
    manifest_jar_path = "dist/export-classpath/manifest.jar"
    pants_run = self.run_pants(["export-classpath",
      "--manifest-jar-only",
      "testprojects/src/java/org/pantsbuild/testproject/exclude:foo"])
    self.assert_success(pants_run)
    self.assertTrue(os.path.exists(manifest_jar_path))

    with open_zip(manifest_jar_path) as synthetic_jar:
      self.assertListEqual([Manifest.PATH], synthetic_jar.namelist())
      oneline_classpath = synthetic_jar.read(Manifest.PATH).replace('\n', '').replace(' ', '')
      self.assertNotIn('sbt-interface', oneline_classpath)
      self.assertIn('foo', oneline_classpath)
      self.assertIn('baz', oneline_classpath)
