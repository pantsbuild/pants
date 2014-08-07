# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ProtobufIntegrationTest(PantsRunIntegrationTest):
  def test_bundle_protobuf_normal(self):
    pants_run = self.run_pants(
        ['goal', 'bundle', 'src/java/com/pants/examples/protobuf:protobuf-example', '--bundle-deployjar'])
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal bundle run expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))
    out_path = os.path.join(get_buildroot(), 'dist', 'protobuf-example-bundle')
    java_run = subprocess.Popen(['java', '-cp', 'protobuf-example.jar',
                                 'com.pants.examples.protobuf.ExampleProtobuf'],
                                stdout=subprocess.PIPE,
                                cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertTrue("parsec" in java_out)

  def test_bundle_protobuf_imports(self):
    pants_run = self.run_pants(
        ['goal', 'bundle', 'src/java/com/pants/examples/protobuf:protobuf-imports-example',
         '--bundle-deployjar'])
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal bundle run expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))
    out_path = os.path.join(get_buildroot(), 'dist', 'protobuf-imports-example-bundle')
    java_run = subprocess.Popen(['java', '-cp', 'protobuf-imports-example.jar',
                                 'com.pants.examples.protobuf.imports.ExampleProtobufImports'],
                                stdout=subprocess.PIPE,
                                cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertTrue("very test" in java_out)
